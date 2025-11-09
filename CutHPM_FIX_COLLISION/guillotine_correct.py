# -*- coding: utf-8 -*-
"""
ПРАВИЛЬНАЯ реализация 3D Guillotine Cutting Algorithm
Строго по описанию из PDF: "3D Guillotine Cutting Algorithm Implementation"

КЛЮЧЕВЫЕ ПРИНЦИПЫ:
1. Каждый рез идет от края до края (full guillotine cut)
2. Последовательность из 3 резов (X, Y, Z) для выделения одной детали
3. После каждого реза: одна часть содержит деталь (продолжаем резать), другая - leftover
4. Kerf вычитается из размеров после каждого реза
5. Рекурсивная обработка всех leftovers
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict
import time


@dataclass
class Part:
    """Деталь для раскроя"""
    id: int
    x: float
    y: float
    z: float
    quantity: int
    priority: int = 0

    def volume(self) -> float:
        return self.x * self.y * self.z


@dataclass
class Block:
    """Блок материала"""
    id: str
    x: float
    y: float
    z: float
    kerf: float = 4.0
    grade: str = None

    def volume(self) -> float:
        return self.x * self.y * self.z


@dataclass
class PlacedPart:
    """Размещенная деталь с позицией"""
    part_id: int
    x: float
    y: float
    z: float
    length: float
    width: float
    height: float

    def overlaps(self, other: 'PlacedPart', kerf: float = 0) -> bool:
        """Проверка пересечения"""
        return not (
            self.x + self.length + kerf <= other.x or
            other.x + other.length + kerf <= self.x or
            self.y + self.width + kerf <= other.y or
            other.y + other.width + kerf <= self.y or
            self.z + self.height + kerf <= other.z or
            other.z + other.height + kerf <= self.z
        )


class GuillotineCutter:
    """
    Guillotine 3D Cutting Algorithm (по PDF спецификации)
    """

    def __init__(self, parts: List[Part], stocks: List[Block]):
        # Сортировка: приоритет сначала, потом по объему (больше первыми)
        self.parts = sorted(parts, key=lambda p: (-p.priority, -p.volume()))
        self.stocks = stocks

        # Результаты
        self.placed_parts: List[PlacedPart] = []
        self.steps = []
        self.step_counter = 0

        # Статистика
        self.total_stock_volume = sum(s.volume() for s in stocks)
        self.total_parts_volume = 0.0
        self.total_cuts = 0

    def find_part_for_block(self, block: Block) -> Tuple[Optional[Part], Optional[Tuple[float, float, float]]]:
        """
        Найти деталь, которая помещается в блок
        Вернуть (Part, (px, py, pz)) или (None, None)

        Стратегия выбора ориентации (из PDF):
        - Минимизировать количество резов
        - Минимизировать объем остатков
        """
        for part in self.parts:
            if part.quantity <= 0:
                continue

            # Все 6 возможных ориентаций
            orientations = [
                (part.x, part.y, part.z),
                (part.x, part.z, part.y),
                (part.y, part.x, part.z),
                (part.y, part.z, part.x),
                (part.z, part.x, part.y),
                (part.z, part.y, part.x)
            ]

            # Удалить дубликаты
            orientations = list(set(orientations))

            best_orientation = None
            best_cuts = 4  # больше максимума
            best_leftover_vol = None

            for (px, py, pz) in orientations:
                if px <= block.x and py <= block.y and pz <= block.z:
                    # Деталь помещается

                    # Подсчет резов
                    cuts = 0
                    if px < block.x:
                        cuts += 1
                    if py < block.y:
                        cuts += 1
                    if pz < block.z:
                        cuts += 1

                    # Объем остатков
                    leftover_vol = block.volume() - (px * py * pz)

                    # Выбор лучшей ориентации: меньше резов, потом меньше остаток
                    if (cuts < best_cuts or
                        (cuts == best_cuts and (best_leftover_vol is None or leftover_vol < best_leftover_vol))):
                        best_cuts = cuts
                        best_leftover_vol = leftover_vol
                        best_orientation = (px, py, pz)

            if best_orientation:
                return part, best_orientation

        return None, None

    def cut_block(self, block: Block, origin: Tuple[float, float, float] = (0, 0, 0),
                  parent_step: Optional[int] = None):
        """
        Рекурсивная резка блока

        Алгоритм (из PDF):
        1. Найти деталь, которая помещается
        2. Сделать до 3 резов (X, Y, Z) чтобы выделить деталь
        3. Каждый рез создает 2 части: одна содержит деталь, другая - leftover
        4. Рекурсивно обработать все leftovers
        """
        # Базовый случай: блок слишком маленький
        if block.x < 10 or block.y < 10 or block.z < 10:
            return

        # Найти деталь
        part, orientation = self.find_part_for_block(block)

        if part is None:
            # Нет детали - блок остается как leftover
            self.steps.append({
                "Step": None,
                "Cut": None,
                "Result": "Leftover",
                "Dimensions": f"{block.x:.0f}x{block.y:.0f}x{block.z:.0f}",
                "Parent": parent_step
            })
            return

        # Ориентация детали
        px, py, pz = orientation
        kerf = block.kerf
        ox, oy, oz = origin  # origin текущего блока в глобальных координатах

        # ====================================================================
        # ПЕРВЫЙ РЕЗ (X-axis) - если нужен
        # ====================================================================
        if px < block.x:
            self.step_counter += 1
            self.total_cuts += 1
            step_num = self.step_counter

            # Два блока после реза:
            # 1. Slab (содержит деталь): размер (px, block.y, block.z)
            # 2. Remainder: размер (block.x - px - kerf, block.y, block.z)

            slab_block = Block(
                id=f"{block.id}_SX",
                x=px,
                y=block.y,
                z=block.z,
                kerf=kerf,
                grade=block.grade
            )
            slab_origin = origin  # slab остается на месте

            remainder_block = Block(
                id=f"{block.id}_RX",
                x=block.x - px - kerf,
                y=block.y,
                z=block.z,
                kerf=kerf,
                grade=block.grade
            )
            remainder_origin = (ox + px + kerf, oy, oz)  # сдвиг по X

            # Логируем
            self.steps.append({
                "Step": step_num,
                "Cut": f"X@{px:.0f}",
                "Result": "Leftover",
                "Dimensions": f"{remainder_block.x:.0f}x{remainder_block.y:.0f}x{remainder_block.z:.0f}",
                "Parent": parent_step
            })
        else:
            # Рез не нужен - деталь занимает всю длину
            slab_block = block
            slab_origin = origin
            step_num = parent_step
            remainder_block = None
            remainder_origin = None

        # ====================================================================
        # ВТОРОЙ РЕЗ (Y-axis) - если нужен
        # ====================================================================
        if py < slab_block.y:
            self.step_counter += 1
            self.total_cuts += 1
            step_num = self.step_counter

            # Два блока после реза:
            # 1. Front (содержит деталь): размер (slab_block.x, py, slab_block.z)
            # 2. Back remainder: размер (slab_block.x, slab_block.y - py - kerf, slab_block.z)

            front_block = Block(
                id=f"{slab_block.id}_SY",
                x=slab_block.x,
                y=py,
                z=slab_block.z,
                kerf=kerf,
                grade=slab_block.grade
            )
            front_origin = slab_origin  # front остается на месте

            back_block = Block(
                id=f"{slab_block.id}_RY",
                x=slab_block.x,
                y=slab_block.y - py - kerf,
                z=slab_block.z,
                kerf=kerf,
                grade=slab_block.grade
            )
            sox, soy, soz = slab_origin
            back_origin = (sox, soy + py + kerf, soz)  # сдвиг по Y

            # Логируем
            self.steps.append({
                "Step": step_num,
                "Cut": f"Y@{py:.0f}",
                "Result": "Leftover",
                "Dimensions": f"{back_block.x:.0f}x{back_block.y:.0f}x{back_block.z:.0f}",
                "Parent": step_num - 1 if px < block.x else parent_step
            })

            slab_block = front_block
            slab_origin = front_origin
            remainder_block2 = back_block
            remainder_origin2 = back_origin
        else:
            # Рез не нужен
            remainder_block2 = None
            remainder_origin2 = None

        # ====================================================================
        # ТРЕТИЙ РЕЗ (Z-axis) - если нужен
        # ====================================================================
        if pz < slab_block.z:
            self.step_counter += 1
            self.total_cuts += 1
            step_num = self.step_counter

            # Два блока после реза:
            # 1. Bottom (это ДЕТАЛЬ!): размер (slab_block.x, slab_block.y, pz)
            # 2. Top remainder: размер (slab_block.x, slab_block.y, slab_block.z - pz - kerf)

            part_block = Block(
                id=f"{slab_block.id}_PART",
                x=slab_block.x,
                y=slab_block.y,
                z=pz,
                kerf=kerf,
                grade=slab_block.grade
            )
            part_origin = slab_origin  # деталь остается на месте

            top_block = Block(
                id=f"{slab_block.id}_RZ",
                x=slab_block.x,
                y=slab_block.y,
                z=slab_block.z - pz - kerf,
                kerf=kerf,
                grade=slab_block.grade
            )
            sox, soy, soz = slab_origin
            top_origin = (sox, soy, soz + pz + kerf)  # сдвиг по Z

            # Логируем
            self.steps.append({
                "Step": step_num,
                "Cut": f"Z@{pz:.0f}",
                "Result": "Leftover",
                "Dimensions": f"{top_block.x:.0f}x{top_block.y:.0f}x{top_block.z:.0f}",
                "Parent": step_num - 1
            })

            remainder_block3 = top_block
            remainder_origin3 = top_origin
        else:
            # Рез не нужен - slab_block сам является деталью
            part_block = slab_block
            part_origin = slab_origin
            remainder_block3 = None
            remainder_origin3 = None

        # ====================================================================
        # ДЕТАЛЬ ВЫДЕЛЕНА!
        # ====================================================================

        # Размещаем деталь
        px_origin, py_origin, pz_origin = part_origin
        placed = PlacedPart(
            part_id=part.id,
            x=px_origin,
            y=py_origin,
            z=pz_origin,
            length=px,
            width=py,
            height=pz
        )
        self.placed_parts.append(placed)

        # Логируем деталь
        self.steps.append({
            "Step": step_num,
            "Cut": None,
            "Result": "Part",
            "Dimensions": f"{px:.0f}x{py:.0f}x{pz:.0f}",
            "Parent": step_num,
            "PartID": part.id
        })

        # Обновляем количество
        part.quantity -= 1
        self.total_parts_volume += (px * py * pz)

        # ====================================================================
        # РЕКУРСИВНО ОБРАБАТЫВАЕМ LEFTOVERS (depth-first)
        # ====================================================================

        # Leftover 3 (Z cut)
        if remainder_block3 and remainder_block3.volume() > 100:
            self.cut_block(remainder_block3, remainder_origin3, step_num)

        # Leftover 2 (Y cut)
        if remainder_block2 and remainder_block2.volume() > 100:
            self.cut_block(remainder_block2, remainder_origin2, step_num)

        # Leftover 1 (X cut)
        if remainder_block and remainder_block.volume() > 100:
            self.cut_block(remainder_block, remainder_origin, step_num)

    def solve(self) -> Tuple[List[PlacedPart], Dict]:
        """Главный метод решения"""
        start_time = time.time()

        # Режем каждый stock блок
        for stock in self.stocks:
            self.cut_block(stock, origin=(0, 0, 0), parent_step=None)

        # Проверка пересечений
        collisions = self._check_collisions()

        # Статистика
        computation_time = time.time() - start_time

        utilization = (self.total_parts_volume / self.total_stock_volume * 100) if self.total_stock_volume > 0 else 0

        # Подсчет деталей
        item_counts = {}
        for placed in self.placed_parts:
            item_counts[placed.part_id] = item_counts.get(placed.part_id, 0) + 1

        stats = {
            'filled_volume': self.total_parts_volume,
            'block_volume': self.total_stock_volume,
            'utilization': utilization,
            'waste': 100 - utilization,
            'item_counts': item_counts,
            'placed_items': self.placed_parts,
            'computation_time': computation_time,
            'collisions': collisions,
            'total_cuts': self.total_cuts,
            'algorithm_used': 'Guillotine3D_PDF_Correct'
        }

        return self.placed_parts, stats

    def _check_collisions(self) -> int:
        """Проверка пересечений деталей"""
        collisions = 0
        n = len(self.placed_parts)
        for i in range(n):
            for j in range(i + 1, n):
                if self.placed_parts[i].overlaps(self.placed_parts[j], 0):
                    collisions += 1
                    print(f"⚠ COLLISION: Part {self.placed_parts[i].part_id} overlaps Part {self.placed_parts[j].part_id}")
                    print(f"  Part {i}: ({self.placed_parts[i].x}, {self.placed_parts[i].y}, {self.placed_parts[i].z}) "
                          f"size ({self.placed_parts[i].length}, {self.placed_parts[i].width}, {self.placed_parts[i].height})")
                    print(f"  Part {j}: ({self.placed_parts[j].x}, {self.placed_parts[j].y}, {self.placed_parts[j].z}) "
                          f"size ({self.placed_parts[j].length}, {self.placed_parts[j].width}, {self.placed_parts[j].height})")
        return collisions
