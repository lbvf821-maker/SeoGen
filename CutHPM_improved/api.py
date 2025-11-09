"""
Простой FastAPI сервер для 3D раскроя.
Использует новую реализацию guillotine3d с учетом количества деталей.
"""
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Tuple, Optional
import guillotine3d
import database
from models import Block
from tree_builder import build_cutting_tree
from reverse_optimization import find_optimal_block_size, suggest_standard_blocks

app = FastAPI(title="AlmaCut3D", version="2.0.0")

# CORS
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Статические файлы
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/")
async def root():
    return FileResponse("frontend/index.html")

# ========== API Models ==========
class ItemModel(BaseModel):
    id: int  # Изменено на int для совместимости
    l: int  # length
    w: int  # width
    h: int  # height
    qty: int = 1  # quantity - количество деталей

class TechModel(BaseModel):
    kerf: float = 4.0  # ширина пропила
    max_cut_length: float = 1400.0
    min_part_size: float = 15.0
    allow_rotations: bool = True

class BlockModel(BaseModel):
    L: float  # length
    W: float  # width
    H: float  # height

class OptimizeRequest(BaseModel):
    block: BlockModel
    items: List[ItemModel]
    tech: TechModel = TechModel()
    iterations: int = 1  # Количество итераций для улучшения результата

class BlockCreateModel(BaseModel):
    material: str
    grade: Optional[str] = None
    length: float
    width: float
    height: float
    quantity: int = 1
    location: Optional[str] = None
    notes: Optional[str] = None

class FindBestBlockRequest(BaseModel):
    items: List[ItemModel]
    material: Optional[str] = None  # Фильтр по материалу
    tech: TechModel = TechModel()
    iterations: int = 3  # Итерации для каждого блока

# ========== API Endpoints ==========
@app.post("/optimize")
def optimize_endpoint(req: OptimizeRequest):
    """Оптимизация раскроя с использованием новой реализации."""
    try:
        # Конвертация в типы guillotine3d
        bin_size = guillotine3d.Bin(
            length=req.block.L,
            width=req.block.W,
            height=req.block.H
        )
        
        items = [
            guillotine3d.Item(
                id=it.id,
                length=it.l,
                width=it.w,
                height=it.h,
                quantity=it.qty
            )
            for it in req.items
        ]
        
        # Оптимизация с несколькими итерациями
        import random
        from algorithm_selector import AlgorithmSelector

        best_pattern = None
        best_stats = None
        best_value = 0

        for iteration in range(max(1, req.iterations)):
            # Перемешиваем порядок деталей для разнообразия (кроме первой итерации)
            items_to_use = items.copy()
            if iteration > 0 and req.iterations > 1:
                random.shuffle(items_to_use)

            # Создаем селектор с автоматическим откатом
            selector = AlgorithmSelector(
                bin_size=bin_size,
                items=items_to_use,
                kerf=req.tech.kerf,
                allow_rotations=req.tech.allow_rotations,
                force_algorithm=None  # Auto-select based on problem size
            )

            # Оптимизация с автоматическим выбором и откатом
            pattern, stats = selector.solve(timeout=60.0)

            # Сохраняем лучший результат
            # ИСПРАВЛЕНО: PDF/almacum возвращают pattern=None, проверяем stats вместо pattern
            if stats and stats.get('filled_volume', 0) > best_value:
                best_value = stats['filled_volume']
                best_pattern = pattern
                best_stats = stats

        if not best_stats:
            raise HTTPException(status_code=500, detail="Не удалось найти решение")
        
        stats = best_stats
        
        # Преобразуем дерево в словарь для JSON сериализации
        def pattern_to_dict(pattern: Optional[guillotine3d.CutPattern]) -> dict:
            if pattern is None:
                return None
            
            result = {
                "length": pattern.length,
                "width": pattern.width,
                "height": pattern.height,
                "value": pattern.value,
                "cut_dir": pattern.cut_dir.name if pattern.cut_dir else None,
                "cut_pos": pattern.cut_pos,
                "item_id": pattern.item_id
            }
            
            if pattern.left_pattern:
                result["left_pattern"] = pattern_to_dict(pattern.left_pattern)
            if pattern.right_pattern:
                result["right_pattern"] = pattern_to_dict(pattern.right_pattern)
            
            return result
        
        tree_dict = pattern_to_dict(best_pattern)

        # Получаем все размещенные детали
        # Сначала пробуем взять из stats (Maximal Spaces / Hybrid возвращают placed_items)
        if 'placed_items' in stats and stats['placed_items']:
            items_placed = [
                {
                    "item_id": placed.item_id,
                    "position": {"x": placed.x, "y": placed.y, "z": placed.z},
                    "dimensions": {"l": placed.length, "w": placed.width, "h": placed.height}
                }
                for placed in stats['placed_items']
            ]
        else:
            # Fallback: используем дерево паттернов (для чистого Guillotine)
            all_items = best_pattern.get_all_items((0, 0, 0), req.tech.kerf) if best_pattern else []
            items_placed = [
                {
                    "item_id": item_id,
                    "position": {"x": pos[0], "y": pos[1], "z": pos[2]},
                    "dimensions": {"l": dims[0], "w": dims[1], "h": dims[2]}
                }
                for item_id, pos, dims in all_items
            ]

        # Построить дерево резов с последовательностью и проверкой конфликтов
        cutting_tree = build_cutting_tree(
            pattern=best_pattern,
            bin_dimensions=(req.block.L, req.block.W, req.block.H),
            kerf=req.tech.kerf
        )
        cutting_tree_data = cutting_tree.to_dict()

        return {
            "filled_volume": stats['filled_volume'],
            "value": best_value,
            "block": [req.block.L, req.block.W, req.block.H],
            "tree": tree_dict,
            "utilization": stats['utilization'],
            "waste": stats['waste'],
            "item_counts": stats['item_counts'],
            "items_placed": items_placed,
            "computation_time": stats['computation_time'],
            "cutting_tree": cutting_tree_data,  # Дерево резов с последовательностью
            "total_cuts": stats.get('total_cuts', cutting_tree_data.get('total_cuts', 0) if cutting_tree_data else 0),  # НОВОЕ: Количество резов!
            "algorithm_used": stats.get('algorithm_used', 'Unknown')  # НОВОЕ: Используемый алгоритм
        }
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"{str(e)}\n{traceback.format_exc()}")


# ========== Block Management Endpoints ==========

@app.get("/blocks")
def get_blocks(material: Optional[str] = None, active_only: bool = True):
    """Получить список всех блоков"""
    try:
        if material:
            blocks = database.get_blocks_by_material(material, active_only)
        else:
            blocks = database.get_all_blocks(active_only)

        return {
            "blocks": [
                {
                    "id": b.id,
                    "material": b.material,
                    "grade": b.grade,
                    "length": b.length,
                    "width": b.width,
                    "height": b.height,
                    "volume": b.volume(),
                    "quantity": b.quantity,
                    "location": b.location,
                    "notes": b.notes,
                    "is_active": b.is_active
                }
                for b in blocks
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/blocks")
def create_block_endpoint(block: BlockCreateModel):
    """Создать новый блок"""
    try:
        new_block = database.create_block(
            material=block.material,
            grade=block.grade,
            length=block.length,
            width=block.width,
            height=block.height,
            quantity=block.quantity,
            location=block.location,
            notes=block.notes
        )
        return {
            "id": new_block.id,
            "material": new_block.material,
            "grade": new_block.grade,
            "length": new_block.length,
            "width": new_block.width,
            "height": new_block.height,
            "quantity": new_block.quantity,
            "location": new_block.location
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/blocks/{block_id}")
def get_block_endpoint(block_id: int):
    """Получить блок по ID"""
    block = database.get_block_by_id(block_id)
    if not block:
        raise HTTPException(status_code=404, detail="Блок не найден")

    return {
        "id": block.id,
        "material": block.material,
        "grade": block.grade,
        "length": block.length,
        "width": block.width,
        "height": block.height,
        "volume": block.volume(),
        "quantity": block.quantity,
        "location": block.location,
        "notes": block.notes,
        "is_active": block.is_active
    }


@app.delete("/blocks/{block_id}")
def delete_block_endpoint(block_id: int, hard_delete: bool = False):
    """Удалить блок"""
    success = database.delete_block(block_id, soft_delete=not hard_delete)
    if not success:
        raise HTTPException(status_code=404, detail="Блок не найден")
    return {"success": True}


# ========== Find Best Block Endpoint ==========

@app.post("/find-best-block")
def find_best_block_endpoint(req: FindBestBlockRequest):
    """
    Найти оптимальный блок из базы данных для заданных деталей.
    Перебирает все доступные блоки и выбирает тот, который дает лучшее заполнение.
    """
    try:
        # Получаем список блоков (фильтруем по материалу если указан)
        if req.material:
            blocks = database.get_blocks_by_material(req.material, active_only=True)
        else:
            blocks = database.get_all_blocks(active_only=True)

        if not blocks:
            raise HTTPException(status_code=404, detail="Нет доступных блоков на складе")

        # Конвертируем детали
        items = [
            guillotine3d.Item(
                id=it.id,
                length=it.l,
                width=it.w,
                height=it.h,
                quantity=it.qty
            )
            for it in req.items
        ]

        # Перебираем все блоки и ищем лучший
        best_result = None
        best_utilization = 0
        best_block = None

        import random

        for block in blocks:
            # Пропускаем блоки с нулевым количеством
            if block.quantity <= 0:
                continue

            bin_size = guillotine3d.Bin(
                length=block.length,
                width=block.width,
                height=block.height
            )

            # Запускаем несколько итераций для этого блока
            for iteration in range(req.iterations):
                items_copy = items.copy()
                if iteration > 0:
                    random.shuffle(items_copy)

                # Используем гибридный алгоритм если запрошено больше 10 деталей
                total_items = sum(item.quantity for item in items_copy)
                use_hybrid = total_items > 10  # Автоматически включаем hybrid

                optimizer = guillotine3d.Guillotine3DCutter(
                    bin_size=bin_size,
                    items=items_copy,
                    kerf=req.tech.kerf,
                    max_cut_length=req.tech.max_cut_length,
                    min_part_size=req.tech.min_part_size,
                    allow_rotations=req.tech.allow_rotations,
                    use_hybrid=use_hybrid  # NEW! Гибридный алгоритм
                )

                pattern, stats = optimizer.solve()

                # Сохраняем лучший результат
                if pattern and stats['utilization'] > best_utilization:
                    best_utilization = stats['utilization']
                    best_result = {
                        "pattern": pattern,
                        "stats": stats,
                        "bin_size": bin_size
                    }
                    best_block = block

        if not best_result:
            raise HTTPException(status_code=500, detail="Не удалось найти решение ни для одного блока")

        # Преобразуем результат
        def pattern_to_dict(pattern: Optional[guillotine3d.CutPattern]) -> dict:
            if pattern is None:
                return None

            result = {
                "length": pattern.length,
                "width": pattern.width,
                "height": pattern.height,
                "value": pattern.value,
                "cut_dir": pattern.cut_dir.name if pattern.cut_dir else None,
                "cut_pos": pattern.cut_pos,
                "item_id": pattern.item_id
            }

            if pattern.left_pattern:
                result["left_pattern"] = pattern_to_dict(pattern.left_pattern)
            if pattern.right_pattern:
                result["right_pattern"] = pattern_to_dict(pattern.right_pattern)

            return result

        tree_dict = pattern_to_dict(best_result["pattern"])

        # Получаем все размещенные детали
        all_items = best_result["pattern"].get_all_items((0, 0, 0), req.tech.kerf)
        items_placed = [
            {
                "item_id": item_id,
                "position": {"x": pos[0], "y": pos[1], "z": pos[2]},
                "dimensions": {"l": dims[0], "w": dims[1], "h": dims[2]}
            }
            for item_id, pos, dims in all_items
        ]

        # Построить дерево резов
        cutting_tree = build_cutting_tree(
            pattern=best_result["pattern"],
            bin_dimensions=(best_block.length, best_block.width, best_block.height),
            kerf=req.tech.kerf
        )
        cutting_tree_data = cutting_tree.to_dict()

        stats = best_result["stats"]

        return {
            "best_block": {
                "id": best_block.id,
                "material": best_block.material,
                "grade": best_block.grade,
                "length": best_block.length,
                "width": best_block.width,
                "height": best_block.height,
                "quantity": best_block.quantity,
                "location": best_block.location
            },
            "filled_volume": stats['filled_volume'],
            "value": stats['best_value'],
            "block": [best_block.length, best_block.width, best_block.height],
            "tree": tree_dict,
            "utilization": stats['utilization'],
            "waste": stats['waste'],
            "item_counts": stats['item_counts'],
            "items_placed": items_placed,
            "computation_time": stats['computation_time'],
            "cutting_tree": cutting_tree_data  # Дерево резов с последовательностью
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"{str(e)}\n{traceback.format_exc()}")


# ========== Reverse Optimization Endpoints ==========

class ReverseOptimizeRequest(BaseModel):
    items: List[ItemModel]
    tech: TechModel = TechModel()
    target_utilization: float = 8.0  # Целевая заполняемость (%)


@app.post("/reverse-optimize")
def reverse_optimize_endpoint(req: ReverseOptimizeRequest):
    """
    Обратная оптимизация - подбор оптимального размера блока для заданных деталей.

    Алгоритм перебирает различные размеры и пропорции блоков,
    находя наименьший блок с приемлемой заполняемостью.
    """
    try:
        # Конвертируем детали
        items = [
            guillotine3d.Item(
                id=it.id,
                length=it.l,
                width=it.w,
                height=it.h,
                quantity=it.qty
            )
            for it in req.items
        ]

        # Запускаем обратную оптимизацию
        result = find_optimal_block_size(
            items=items,
            kerf=req.tech.kerf,
            allow_rotations=req.tech.allow_rotations,
            target_utilization=req.target_utilization
        )

        if not result['success']:
            raise HTTPException(status_code=500, detail=result.get('message', 'Не удалось найти решение'))

        # Преобразуем паттерн
        def pattern_to_dict(pattern: Optional[guillotine3d.CutPattern]) -> dict:
            if pattern is None:
                return None

            result_dict = {
                "length": pattern.length,
                "width": pattern.width,
                "height": pattern.height,
                "value": pattern.value,
                "cut_dir": pattern.cut_dir.name if pattern.cut_dir else None,
                "cut_pos": pattern.cut_pos,
                "item_id": pattern.item_id
            }

            if pattern.left_pattern:
                result_dict["left_pattern"] = pattern_to_dict(pattern.left_pattern)
            if pattern.right_pattern:
                result_dict["right_pattern"] = pattern_to_dict(pattern.right_pattern)

            return result_dict

        tree_dict = pattern_to_dict(result['pattern'])

        # Получаем размещенные детали
        all_items = result['pattern'].get_all_items((0, 0, 0), req.tech.kerf)
        items_placed = [
            {
                "item_id": item_id,
                "position": {"x": pos[0], "y": pos[1], "z": pos[2]},
                "dimensions": {"l": dims[0], "w": dims[1], "h": dims[2]}
            }
            for item_id, pos, dims in all_items
        ]

        L, W, H = result['best_block_size']

        return {
            "success": True,
            "best_block_size": {"L": L, "W": W, "H": H},
            "block_volume": result['block_volume'],
            "utilization": result['utilization'],
            "filled_volume": result['filled_volume'],
            "waste": result['waste'],
            "tree": tree_dict,
            "items_placed": items_placed,
            "cutting_tree": result['cutting_tree'],
            "alternative_sizes": result['all_results'],
            "stats": result['stats']
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"{str(e)}\n{traceback.format_exc()}")


@app.post("/suggest-standard-blocks")
def suggest_standard_blocks_endpoint(req: FindBestBlockRequest):
    """
    Предложить стандартные размеры блоков из типового ряда.

    Проверяет стандартные размеры металлопроката и находит
    наиболее подходящий для заданных деталей.
    """
    try:
        # Конвертируем детали
        items = [
            guillotine3d.Item(
                id=it.id,
                length=it.l,
                width=it.w,
                height=it.h,
                quantity=it.qty
            )
            for it in req.items
        ]

        # Получаем рекомендации по стандартным блокам
        results = suggest_standard_blocks(
            items=items,
            kerf=req.tech.kerf,
            allow_rotations=req.tech.allow_rotations
        )

        if not results:
            raise HTTPException(status_code=404, detail="Не найдено подходящих стандартных размеров")

        # Форматируем результаты
        formatted_results = []
        for r in results[:10]:  # Топ 10
            L, W, H = r['block_size']
            formatted_results.append({
                "block_size": {"L": L, "W": W, "H": H},
                "volume": r['volume'],
                "utilization": r['utilization'],
                "filled_volume": r['filled_volume'],
                "waste": r['waste'],
                "is_standard": r['is_standard']
            })

        return {
            "success": True,
            "standard_blocks": formatted_results,
            "total_found": len(results)
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"{str(e)}\n{traceback.format_exc()}")


# ========== Initialize Database on Startup ==========

@app.on_event("startup")
def startup_event():
    """Инициализация БД при запуске сервера"""
    try:
        database.init_db()
        print("[OK] База данных инициализирована")

        # Проверяем есть ли блоки, если нет - добавляем тестовые данные
        blocks = database.get_all_blocks(active_only=False)
        if len(blocks) == 0:
            print("[INFO] База данных пуста, добавляем тестовые блоки...")
            database.populate_sample_data()
    except Exception as e:
        print(f"[ERROR] Ошибка инициализации БД: {e}")


if __name__ == "__main__":
    import uvicorn
    import os
    from utils import load_env
    load_env()  # Загружаем переменные из .env
    PORT = int(os.getenv("PORT", "3000"))
    uvicorn.run(app, host="127.0.0.1", port=PORT)

