# -*- coding: utf-8 -*-
"""
Умный селектор алгоритмов с автоматическим откатом
"""

import guillotine3d
from hybrid_guillotine import HybridGuillotinePacking
from almacum_guillotine import AlmaCumGuillotine
from guillotine_pdf import GuillotinePDF
from improved_guillotine import ImprovedGuillotine, Item as ImprovedItem, PlacedItem as ImprovedPlacedItem
from guillotine_correct import GuillotineCutter, Part, Block, PlacedPart as CorrectPlacedPart
from dp_guillotine_rrp import (
    Item as DPItem, Stock as DPStock, DPGuillotineSolver,
    expand_plan_to_items, check_collisions, PlacedItem
)
from typing import List, Tuple, Dict, Optional
import time


class AlgorithmSelector:
    """
    Автоматически выбирает лучший алгоритм на основе характеристик задачи
    С автоматическим откатом на более простые алгоритмы при неудаче
    """

    def __init__(self, bin_size: guillotine3d.Bin, items: List[guillotine3d.Item],
                 kerf: float = 4.0, allow_rotations: bool = True,
                 force_algorithm: Optional[str] = None):
        self.bin = bin_size
        self.items = items
        self.kerf = kerf
        self.allow_rotations = allow_rotations
        self.force_algorithm = force_algorithm

    def solve(self, timeout: float = 60.0) -> Tuple[Optional[guillotine3d.CutPattern], Dict]:
        """
        Оптимизация с автоматическим выбором алгоритма и откатом
        """
        total_items = sum(item.quantity for item in self.items)

        # Определить алгоритм
        if self.force_algorithm:
            algorithm = self.force_algorithm
        else:
            algorithm = self._select_algorithm(total_items)

        pass
        pass
        pass
        pass
        pass
        pass
        # Попытка запустить выбранный алгоритм
        start_time = time.time()
        pattern, stats = self._run_algorithm(algorithm, timeout)

        # Если не удалось - откат
        # ИСПРАВЛЕНО: Проверяем placed_items вместо item_counts (PDF/almacum используют placed_items)
        has_results = (len(stats.get('placed_items', [])) > 0 or
                      len(stats.get('item_counts', {})) > 0)

        if not stats or not has_results:
            pass
            pattern, stats = self._fallback(algorithm, timeout - (time.time() - start_time))

        # Добавить информацию об использованном алгоритме
        if stats:
            stats['algorithm_used'] = algorithm

        return pattern, stats

    def _select_algorithm(self, total_items: int) -> str:
        """
        Выбрать алгоритм на основе количества деталей
        """
        # НОВЫЙ УЛУЧШЕННЫЙ АЛГОРИТМ: ImprovedGuillotine
        # - Beam search + lookahead
        # - Учет max_cut_length
        # - Несколько стратегий сортировки
        # - Целевая утилизация 40-50%
        return 'improved'  # NEW: Improved Guillotine with beam search

    def _run_algorithm(self, algorithm: str, timeout: float) -> Tuple[Optional[guillotine3d.CutPattern], Dict]:
        """
        Запустить конкретный алгоритм
        """
        print(f"\n{'='*80}")
        print(f"DEBUG: Running algorithm: {algorithm}")
        print(f"DEBUG: Kerf value: {self.kerf}")
        print(f"DEBUG: Block dimensions: {self.bin.length}x{self.bin.width}x{self.bin.height}")
        print(f"DEBUG: Number of item types: {len(self.items)}")
        print(f"DEBUG: Total items: {sum(item.quantity for item in self.items)}")
        print(f"{'='*80}\n")
        try:

            if algorithm == 'improved':
                # CORRECTED: Using PDF-based guillotine algorithm (guillotine_correct.py)
                # This implementation follows the exact specification from the PDF:
                # - Sequential X, Y, Z cuts with proper origin tracking
                # - Correct remainder calculation after each cut
                # - Collision-free placement with global coordinates

                # Convert items to Part format
                parts = []
                for item in self.items:
                    parts.append(Part(
                        id=item.id,
                        x=item.length,
                        y=item.width,
                        z=item.height,
                        quantity=item.quantity,
                        priority=0  # Can be adjusted if needed
                    ))

                # Create Block (stock)
                stock = Block(
                    id="STOCK_1",
                    x=self.bin.length,
                    y=self.bin.width,
                    z=self.bin.height,
                    kerf=self.kerf,
                    grade=None
                )

                # Run the correct guillotine algorithm
                cutter = GuillotineCutter(parts=parts, stocks=[stock])
                placed_parts, stats = cutter.solve()

                print(f"✅ Correct Guillotine Algorithm: {len(placed_parts)} items placed")
                print(f"   Utilization: {stats.get('utilization', 0):.2f}%")
                print(f"   Total cuts: {stats.get('total_cuts', 0)}")
                print(f"   Collisions: {stats.get('collisions', 0)}")

                # Convert PlacedPart to dict format for API
                stats['placed_items'] = [
                    {
                        'item_id': p.part_id,
                        'position': {'x': p.x, 'y': p.y, 'z': p.z},
                        'dimensions': {
                            'l': p.length,
                            'w': p.width,
                            'h': p.height
                        }
                    }
                    for p in placed_parts
                ]

                return None, stats  # API uses stats['placed_items']

            elif algorithm == 'pdf':
                # NEW: PDF-based recursive guillotine
                packer = GuillotinePDF(
                    block_L=self.bin.length,
                    block_W=self.bin.width,
                    block_H=self.bin.height,
                    items=self.items,
                    kerf=self.kerf,
                    allow_rotations=self.allow_rotations
                )
                placed_items, stats = packer.solve()

                print(f"PDF Algorithm: {len(placed_items)} items placed")
                print(f"Utilization: {stats.get('utilization', 0):.2f}%")
                print(f"Collisions: {stats.get('collisions', 0)}")

                return None, stats  # API uses stats['placed_items']

            elif algorithm == 'dp_rrp':
                # DP + RRP - production-ready algorithm
                # Convert items to DP format
                # ИСПРАВЛЕНО: передаём quantity напрямую, БЕЗ цикла!
                dp_items = []
                for item in self.items:
                    dp_items.append(DPItem(
                        id=str(item.id),
                        x=int(item.length),
                        y=int(item.width),
                        z=int(item.height),
                        quantity=item.quantity,  # Передаём quantity напрямую!
                        allow_rotation=self.allow_rotations
                    ))

                stock = DPStock(
                    Lx=int(self.bin.length),
                    Ly=int(self.bin.width),
                    Lz=int(self.bin.height),
                    kerf=int(self.kerf),
                    min_slice=10,
                    stage_order=("Z", "X", "Y")
                )

                solver = DPGuillotineSolver(stock, dp_items)
                plan = solver.solve()

                # Expand to placed items
                placed_items_list = expand_plan_to_items(plan, self.kerf)

                # CRITICAL: Check collisions
                collisions = check_collisions(placed_items_list, self.kerf)

                # Convert to stats format
                stats = {
                    'filled_volume': plan.packed_value,
                    'block_volume': float(stock.Lx * stock.Ly * stock.Lz),
                    'utilization': plan.utilization * 100,
                    'waste': (1 - plan.utilization) * 100,
                    'item_counts': plan.counts_by_item,
                    'placed_items': placed_items_list,
                    'collisions': collisions,
                    'algorithm_used': 'DP_RRP_Production'
                }

                # Create dummy pattern for compatibility (API expects CutPattern)
                # We'll use placed_items from stats instead
                pattern = None  # API will use stats['placed_items']

                return pattern, stats

            elif algorithm == 'almacum':
                # AlmaCum guillotine - быстрый и безопасный
                packer = AlmaCumGuillotine(
                    block_L=int(self.bin.length),
                    block_W=int(self.bin.width),
                    block_H=int(self.bin.height),
                    items=self.items,
                    kerf=self.kerf
                )
                placed_items, cutting_tree, stats = packer.solve()

                # Convert PlacedItem to stats format for API
                # AlmaCum already returns placed_items in stats
                print(f"DEBUG: AlmaCum placed {len(placed_items)} items")
                print(f"DEBUG: Collisions detected: {stats.get('collisions', 'N/A')}")
                print(f"DEBUG: Utilization: {stats.get('utilization', 0):.2f}%")

                return None, stats  # API uses stats['placed_items']

            elif algorithm == 'hybrid':
                packer = HybridGuillotinePacking(
                    bin_size=self.bin,
                    items=self.items,
                    kerf=self.kerf,
                    allow_rotations=self.allow_rotations
                )
                return packer.solve()

            elif algorithm == 'advanced':
                # Advanced пока недоступен - используем hybrid
                packer = HybridGuillotinePacking(
                    bin_size=self.bin,
                    items=self.items,
                    kerf=self.kerf,
                    allow_rotations=self.allow_rotations
                )
                return packer.solve()

            elif algorithm == 'dp3uk':
                optimizer = guillotine3d.Guillotine3DCutter(
                    bin_size=self.bin,
                    items=self.items,
                    kerf=self.kerf,
                    allow_rotations=self.allow_rotations,
                    use_hybrid=False
                )
                return optimizer.solve()

            else:
                # По умолчанию - dp_rrp
                return self._run_algorithm('dp_rrp', timeout)

        except Exception as e:
            pass
            return None, {}

    def _fallback(self, failed_algorithm: str, remaining_time: float) -> Tuple[Optional[guillotine3d.CutPattern], Dict]:
        """
        Откат на более простой алгоритм при неудаче
        """
        if remaining_time <= 0:
            pass
            return None, {}

        # Цепочка отката: advanced -> hybrid -> dp3uk
        if failed_algorithm == 'advanced':
            pass
            pattern, stats = self._run_algorithm('hybrid', remaining_time)
            if not pattern:
                pass
                return self._run_algorithm('dp3uk', remaining_time)
            return pattern, stats

        elif failed_algorithm == 'hybrid':
            pass
            return self._run_algorithm('dp3uk', remaining_time)

        else:
            # Если dp3uk не сработал - попробовать hybrid как последнюю надежду
            pass
            return self._run_algorithm('hybrid', remaining_time)
