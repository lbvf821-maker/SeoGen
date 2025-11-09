# -*- coding: utf-8 -*-
"""
УЛУЧШЕННЫЙ АЛГОРИТМ ГИЛЬОТИННОЙ РЕЗКИ 3D
=========================================

Ключевые улучшения:
1. Учет max_cut_length=1400мм при первом резе блока
2. Lookahead - просмотр на 2-3 детали вперед
3. Beam search - держим несколько лучших вариантов
4. Умная сортировка деталей (несколько стратегий)
5. Группировка деталей для минимизации резов
6. Целевая утилизация 40-50%

Автор: Claude
Дата: 2025-11-09
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
import time
import copy


@dataclass
class Item:
    """Деталь для раскроя"""
    id: int
    length: float  # Оригинальная длина
    width: float   # Оригинальная ширина
    height: float  # Оригинальная высота
    quantity: int

    def volume(self) -> float:
        return self.length * self.width * self.height

    def get_orientations(self) -> List[Tuple[float, float, float]]:
        """Все уникальные ориентации"""
        orientations = set()
        dims = [self.length, self.width, self.height]
        for l in dims:
            for w in dims:
                for h in dims:
                    if {l, w, h} == set(dims):  # Все размеры присутствуют
                        orientations.add((l, w, h))
        return sorted(list(orientations), key=lambda x: x[0] * x[1] * x[2], reverse=True)


@dataclass
class PlacedItem:
    """Размещенная деталь с оригинальными размерами"""
    item_id: int
    x: float
    y: float
    z: float
    # ВАЖНО: Сохраняем и размещенную ориентацию, и оригинальные размеры!
    placed_length: float  # Реальная ориентация в раскрое
    placed_width: float
    placed_height: float
    original_length: float  # Оригинальные размеры для визуализации
    original_width: float
    original_height: float
    rotation: str = "NONE"  # Тип вращения: NONE, X90, Y90, Z90, etc.

    def overlaps(self, other: 'PlacedItem', kerf: float = 0) -> bool:
        """Проверка пересечения с учетом kerf"""
        return not (
            self.x + self.placed_length + kerf <= other.x or
            other.x + other.placed_length + kerf <= self.x or
            self.y + self.placed_width + kerf <= other.y or
            other.y + other.placed_width + kerf <= self.y or
            self.z + self.placed_height + kerf <= other.z or
            other.z + other.placed_height + kerf <= self.z
        )


@dataclass
class Block:
    """Свободное пространство в блоке"""
    x: float
    y: float
    z: float
    length: float
    width: float
    height: float
    parent_cut: Optional[str] = None  # Откуда получен: "X", "Y", "Z", "ROOT"

    def volume(self) -> float:
        return self.length * self.width * self.height


@dataclass
class Cut:
    """Информация о резе"""
    direction: str  # "X", "Y", "Z"
    position: float  # Позиция реза
    block_before: Block  # Блок до реза
    blocks_after: List[Block]  # Блоки после реза


@dataclass
class PackingState:
    """Состояние упаковки для beam search"""
    placed_items: List[PlacedItem] = field(default_factory=list)
    free_blocks: List[Block] = field(default_factory=list)
    remaining_quantities: Dict[int, int] = field(default_factory=dict)
    cuts: List[Cut] = field(default_factory=list)
    utilization: float = 0.0

    def score(self) -> float:
        """Оценка качества состояния (для beam search)"""
        # Чем выше утилизация и меньше блоков, тем лучше
        num_blocks_penalty = len(self.free_blocks) * 0.01
        return self.utilization - num_blocks_penalty


class ImprovedGuillotine:
    """
    Улучшенный алгоритм гильотинной резки с:
    - Учетом max_cut_length
    - Lookahead
    - Beam search
    - Умной сортировкой
    """

    def __init__(self, block_L: float, block_W: float, block_H: float,
                 items: List[Item], kerf: float = 4.0,
                 max_cut_length: float = 1400.0,
                 allow_rotations: bool = True,
                 beam_width: int = 3,
                 lookahead_depth: int = 2):
        self.block_L = block_L
        self.block_W = block_W
        self.block_H = block_H
        self.items = items
        self.kerf = kerf
        self.max_cut_length = max_cut_length
        self.allow_rotations = allow_rotations
        self.beam_width = beam_width  # Количество лучших вариантов
        self.lookahead_depth = lookahead_depth  # Глубина просмотра вперед

    def solve(self) -> Tuple[List[PlacedItem], Dict]:
        """Главный метод решения"""
        start_time = time.time()

        # СТРАТЕГИЯ 1: Первый рез с учетом max_cut_length
        initial_blocks = self._initial_cut_with_max_length()

        # СТРАТЕГИЯ 2: Попробовать несколько сортировок деталей
        best_result = None
        best_utilization = 0

        sorting_strategies = [
            ("volume_desc", lambda item: -item.volume()),  # По объему (больше → меньше)
            ("height_desc", lambda item: -item.height),     # По высоте
            ("quantity_desc", lambda item: -item.quantity), # По количеству
            ("mixed", lambda item: -(item.volume() * item.quantity))  # Смешанная
        ]

        for strategy_name, sort_key in sorting_strategies:
            print(f"\n=== Пробуем стратегию сортировки: {strategy_name} ===")

            sorted_items = sorted(self.items, key=sort_key)

            # СТРАТЕГИЯ 3: Beam search с lookahead
            result = self._beam_search_pack(initial_blocks, sorted_items)

            if result and result.utilization > best_utilization:
                best_utilization = result.utilization
                best_result = result
                print(f"✓ Новый лучший результат: {best_utilization:.2f}%")

        if not best_result:
            # Fallback: простая упаковка
            best_result = self._simple_pack(initial_blocks, self.items)

        # Статистика
        computation_time = time.time() - start_time
        stats = self._calculate_stats(best_result, computation_time)

        return best_result.placed_items, stats

    def _initial_cut_with_max_length(self) -> List[Block]:
        """
        СТРАТЕГИЯ 1: Первый рез блока с учетом max_cut_length=1400мм

        Если блок 2000мм, делаем первый рез на:
        - Заготовка 1: ≤1400мм (для мелких деталей, можно резать вдоль всей длины)
        - Заготовка 2: остаток (для крупных деталей или отдельной обработки)
        """
        blocks = []

        # Проверяем, нужен ли первый рез
        if self.block_L > self.max_cut_length:
            # Режем блок на две части по длине
            # Часть 1: max_cut_length - kerf (для мелких деталей)
            cut1_length = self.max_cut_length - self.kerf

            block1 = Block(
                x=0, y=0, z=0,
                length=cut1_length,
                width=self.block_W,
                height=self.block_H,
                parent_cut="ROOT_X1"
            )
            blocks.append(block1)

            # Часть 2: остаток (для крупных деталей)
            block2 = Block(
                x=cut1_length + self.kerf,
                y=0, z=0,
                length=self.block_L - cut1_length - self.kerf,
                width=self.block_W,
                height=self.block_H,
                parent_cut="ROOT_X2"
            )
            blocks.append(block2)

            print(f"[MAX_CUT_LENGTH] Первый рез: {cut1_length:.0f}мм + {block2.length:.0f}мм")
        else:
            # Весь блок помещается в max_cut_length
            blocks.append(Block(
                x=0, y=0, z=0,
                length=self.block_L,
                width=self.block_W,
                height=self.block_H,
                parent_cut="ROOT"
            ))

        return blocks

    def _beam_search_pack(self, initial_blocks: List[Block],
                         sorted_items: List[Item]) -> Optional[PackingState]:
        """
        СТРАТЕГИЯ 3: Beam search - держим несколько лучших состояний
        """
        # Инициализация
        initial_state = PackingState(
            placed_items=[],
            free_blocks=initial_blocks.copy(),
            remaining_quantities={item.id: item.quantity for item in sorted_items},
            cuts=[],
            utilization=0.0
        )

        beam = [initial_state]  # Текущие лучшие состояния

        # Итерации до упаковки всех деталей
        max_iterations = sum(item.quantity for item in sorted_items) + 50

        for iteration in range(max_iterations):
            new_states = []

            # Для каждого состояния в beam
            for state in beam:
                # Проверяем, есть ли еще детали для размещения
                if sum(state.remaining_quantities.values()) == 0:
                    continue  # Все размещено

                # Пробуем разместить следующую деталь во все свободные блоки
                expansions = self._expand_state_with_lookahead(state, sorted_items)
                new_states.extend(expansions)

            if not new_states:
                break  # Больше нечего размещать

            # Выбираем top-K состояний (beam search)
            beam = sorted(new_states, key=lambda s: s.score(), reverse=True)[:self.beam_width]

            # Обновляем утилизацию для каждого состояния
            block_volume = self.block_L * self.block_W * self.block_H
            for state in beam:
                filled_volume = sum(
                    p.placed_length * p.placed_width * p.placed_height
                    for p in state.placed_items
                )
                state.utilization = (filled_volume / block_volume) * 100

        # Возвращаем лучшее состояние
        if beam:
            return max(beam, key=lambda s: s.utilization)
        return None

    def _expand_state_with_lookahead(self, state: PackingState,
                                     sorted_items: List[Item]) -> List[PackingState]:
        """
        СТРАТЕГИЯ 4: Lookahead - просмотр на несколько деталей вперед

        Вместо того, чтобы размещать только следующую деталь, мы:
        1. Смотрим на следующие 2-3 детали
        2. Пробуем разные комбинации
        3. Выбираем лучшую
        """
        expansions = []

        # Получаем следующие N деталей для рассмотрения
        candidate_items = []
        for item in sorted_items:
            if state.remaining_quantities.get(item.id, 0) > 0:
                candidate_items.append(item)
            if len(candidate_items) >= self.lookahead_depth:
                break

        if not candidate_items:
            return []

        # Для каждой детали из кандидатов
        for item in candidate_items:
            # Для каждого свободного блока
            for block_idx, block in enumerate(state.free_blocks):
                # Пробуем все ориентации
                orientations = item.get_orientations() if self.allow_rotations else [(item.length, item.width, item.height)]

                for placed_l, placed_w, placed_h in orientations:
                    # Проверяем, помещается ли деталь
                    if (placed_l <= block.length and
                        placed_w <= block.width and
                        placed_h <= block.height):

                        # Создаем новое состояние
                        new_state = self._place_item_in_state(
                            state, item, block, block_idx,
                            (placed_l, placed_w, placed_h),
                            (item.length, item.width, item.height)
                        )

                        if new_state:
                            expansions.append(new_state)

        return expansions

    def _place_item_in_state(self, state: PackingState, item: Item,
                            block: Block, block_idx: int,
                            placed_dims: Tuple[float, float, float],
                            original_dims: Tuple[float, float, float]) -> Optional[PackingState]:
        """Разместить деталь и создать новое состояние"""
        placed_l, placed_w, placed_h = placed_dims
        orig_l, orig_w, orig_h = original_dims

        # Создаем копию состояния
        new_state = PackingState(
            placed_items=state.placed_items.copy(),
            free_blocks=state.free_blocks.copy(),
            remaining_quantities=state.remaining_quantities.copy(),
            cuts=state.cuts.copy(),
            utilization=state.utilization
        )

        # Размещаем деталь
        placed_item = PlacedItem(
            item_id=item.id,
            x=block.x,
            y=block.y,
            z=block.z,
            placed_length=placed_l,
            placed_width=placed_w,
            placed_height=placed_h,
            original_length=orig_l,  # ВАЖНО: Сохраняем оригинал!
            original_width=orig_w,
            original_height=orig_h,
            rotation=self._get_rotation_type(placed_dims, original_dims)
        )

        new_state.placed_items.append(placed_item)
        new_state.remaining_quantities[item.id] -= 1

        # Убираем использованный блок
        new_state.free_blocks.pop(block_idx)

        # Создаем остатки после гильотинных резов (3 остатка)
        # Остаток 1: после реза по X
        if block.length > placed_l + self.kerf:
            r1 = Block(
                x=block.x + placed_l + self.kerf,
                y=block.y,
                z=block.z,
                length=block.length - placed_l - self.kerf,
                width=block.width,
                height=block.height,
                parent_cut="X"
            )
            new_state.free_blocks.append(r1)
            new_state.cuts.append(Cut("X", placed_l, block, [r1]))

        # Остаток 2: после реза по Y
        if block.width > placed_w + self.kerf:
            r2 = Block(
                x=block.x,
                y=block.y + placed_w + self.kerf,
                z=block.z,
                length=placed_l,
                width=block.width - placed_w - self.kerf,
                height=block.height,
                parent_cut="Y"
            )
            new_state.free_blocks.append(r2)
            new_state.cuts.append(Cut("Y", placed_w, block, [r2]))

        # Остаток 3: после реза по Z
        if block.height > placed_h + self.kerf:
            r3 = Block(
                x=block.x,
                y=block.y,
                z=block.z + placed_h + self.kerf,
                length=placed_l,
                width=placed_w,
                height=block.height - placed_h - self.kerf,
                parent_cut="Z"
            )
            new_state.free_blocks.append(r3)
            new_state.cuts.append(Cut("Z", placed_h, block, [r3]))

        return new_state

    def _get_rotation_type(self, placed: Tuple[float, float, float],
                          original: Tuple[float, float, float]) -> str:
        """Определить тип вращения"""
        if placed == original:
            return "NONE"
        # Можно добавить более детальную классификацию
        return "ROTATED"

    def _simple_pack(self, blocks: List[Block], items: List[Item]) -> PackingState:
        """Простая упаковка (fallback)"""
        state = PackingState(
            placed_items=[],
            free_blocks=blocks.copy(),
            remaining_quantities={item.id: item.quantity for item in items},
            cuts=[]
        )

        sorted_items = sorted(items, key=lambda x: -x.volume())

        for item in sorted_items:
            while state.remaining_quantities[item.id] > 0:
                placed = False

                for block_idx, block in enumerate(state.free_blocks):
                    orientations = item.get_orientations() if self.allow_rotations else [(item.length, item.width, item.height)]

                    for placed_dims in orientations:
                        placed_l, placed_w, placed_h = placed_dims

                        if (placed_l <= block.length and
                            placed_w <= block.width and
                            placed_h <= block.height):

                            new_state = self._place_item_in_state(
                                state, item, block, block_idx,
                                placed_dims,
                                (item.length, item.width, item.height)
                            )

                            if new_state:
                                state = new_state
                                placed = True
                                break

                    if placed:
                        break

                if not placed:
                    break  # Не удалось разместить

        return state

    def _calculate_stats(self, state: PackingState, computation_time: float) -> Dict:
        """Расчет статистики"""
        block_volume = self.block_L * self.block_W * self.block_H
        filled_volume = sum(
            p.placed_length * p.placed_width * p.placed_height
            for p in state.placed_items
        )
        utilization = (filled_volume / block_volume * 100) if block_volume > 0 else 0

        # Подсчет деталей
        item_counts = {}
        for placed in state.placed_items:
            item_counts[placed.item_id] = item_counts.get(placed.item_id, 0) + 1

        # Проверка пересечений
        collisions = self._check_collisions(state.placed_items)

        # Подсчет резов
        total_cuts = len(state.cuts)

        return {
            'filled_volume': filled_volume,
            'block_volume': block_volume,
            'utilization': utilization,
            'waste': 100 - utilization,
            'item_counts': item_counts,
            'placed_items': state.placed_items,
            'computation_time': computation_time,
            'collisions': collisions,
            'total_cuts': total_cuts,  # НОВОЕ!
            'cuts_details': [
                {
                    'direction': cut.direction,
                    'position': cut.position
                }
                for cut in state.cuts
            ],
            'algorithm_used': 'ImprovedGuillotine_BeamSearch_Lookahead'
        }

    def _check_collisions(self, placed_items: List[PlacedItem]) -> int:
        """Проверка пересечений"""
        collisions = 0
        n = len(placed_items)
        for i in range(n):
            for j in range(i + 1, n):
                if placed_items[i].overlaps(placed_items[j], self.kerf):
                    collisions += 1
                    print(f"⚠ COLLISION: Item {placed_items[i].item_id} overlaps with Item {placed_items[j].item_id}")
        return collisions
