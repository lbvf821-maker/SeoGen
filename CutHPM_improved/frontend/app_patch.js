// Patch for app.js to add multi-mode support and stats table
// This script overrides the run button handler to support 3 modes:
// 1. Manual - user specifies block dimensions
// 2. Database - select block from database
// 3. Reverse - auto-find optimal block size

(function() {
    // Wait for DOM to be ready
    function initPatch() {
        const runBtn = document.getElementById('run');
        if (!runBtn) {
            console.error('Run button not found, retrying...');
            setTimeout(initPatch, 100);
            return;
        }

        // Replace the onclick handler
        runBtn.onclick = async () => {
            try {
                // Determine active mode
                const mode = document.querySelector('input[name="mode"]:checked')?.value || 'manual';

                let blockL, blockW, blockH;
                const kerf = parseFloat(document.getElementById('kerf').value);
                const allowRotations = document.getElementById('allowRotations').checked;
                const iterations = parseInt(document.getElementById('iterations').value) || 3;

                const itemsText = document.getElementById('items').value;
                const items = itemsText.split('\n').filter(l => l.trim()).map(line => {
                    const parts = line.split(',');
                    const [id, l, w, h, qty] = parts;
                    return {
                        id: parseInt(id.trim()),
                        l: parseFloat(l),
                        w: parseFloat(w),
                        h: parseFloat(h),
                        qty: parseInt(qty || 1)
                    };
                });

                runBtn.disabled = true;
                runBtn.textContent = 'Вычисление...';

                let response, result;

                if (mode === 'reverse') {
                    // Reverse optimization mode
                    const targetUtil = parseFloat(document.getElementById('targetUtil')?.value) || 80;

                    response = await fetch('/reverse-optimize', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            items: items,
                            tech: {kerf, allow_rotations: allowRotations},
                            target_utilization: targetUtil
                        })
                    });

                    if (!response.ok) {
                        const errorText = await response.text();
                        throw new Error(`HTTP ${response.status}: ${errorText}`);
                    }

                    result = await response.json();
                    blockL = result.best_block_size.L;
                    blockW = result.best_block_size.W;
                    blockH = result.best_block_size.H;

                    // Update UI
                    document.getElementById('blockL').value = blockL;
                    document.getElementById('blockW').value = blockW;
                    document.getElementById('blockH').value = blockH;

                } else if (mode === 'database') {
                    // Database mode
                    const materialFilter = document.getElementById('materialFilter')?.value;

                    response = await fetch('/find-best-block', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            items: items,
                            material: materialFilter || null,
                            tech: {kerf, allow_rotations: allowRotations},
                            iterations: iterations
                        })
                    });

                    if (!response.ok) {
                        const errorText = await response.text();
                        throw new Error(`HTTP ${response.status}: ${errorText}`);
                    }

                    result = await response.json();
                    blockL = result.best_block.length;
                    blockW = result.best_block.width;
                    blockH = result.best_block.height;

                    // Update UI
                    document.getElementById('blockL').value = blockL;
                    document.getElementById('blockW').value = blockW;
                    document.getElementById('blockH').value = blockH;

                } else {
                    // Manual mode
                    blockL = parseFloat(document.getElementById('blockL').value);
                    blockW = parseFloat(document.getElementById('blockW').value);
                    blockH = parseFloat(document.getElementById('blockH').value);

                    response = await fetch('/optimize', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            block: {L: blockL, W: blockW, H: blockH},
                            items: items,
                            tech: {kerf, allow_rotations: allowRotations},
                            iterations: iterations
                        })
                    });

                    if (!response.ok) {
                        const errorText = await response.text();
                        throw new Error(`HTTP ${response.status}: ${errorText}`);
                    }

                    result = await response.json();
                }

                console.log('API Response:', result);

                if (!result) {
                    throw new Error('Не получен ответ от сервера');
                }

                // Clear scene and render (call global functions from app.js)
                if (typeof clearScene === 'function') clearScene();
                window.currentBlockDims = [blockL, blockW, blockH];

                // Add block wireframe
                if (typeof addBlockWireframe === 'function') {
                    window.blockWireframe = addBlockWireframe(0, 0, 0, blockL, blockW, blockH);
                }

                // Sub-blocks visualization enabled
                if (result.cutting_tree && typeof visualizeSubBlocks === 'function') {
                    visualizeSubBlocks(result.cutting_tree);
                }

                // Render items
                const itemColorMap = {};
                const itemIndexMap = {};

                if (result.items_placed && result.items_placed.length > 0 && typeof addBox === 'function') {
                    result.items_placed.forEach(item => {
                        const itemId = item.item_id;
                        const pos = item.position;
                        const dims = item.dimensions;

                        if (!itemColorMap[itemId]) {
                            itemIndexMap[itemId] = Object.keys(itemColorMap).length;
                            if (typeof getItemColor === 'function') {
                                itemColorMap[itemId] = getItemColor(String(itemId), itemIndexMap[itemId]);
                            }
                        }

                        addBox(pos.x, pos.y, pos.z, dims.l, dims.w, dims.h,
                               itemColorMap[itemId], window.currentOpacity || 1.0, String(itemId), false);
                    });
                }

                // Update camera
                if (window.camera && window.controls) {
                    const maxDim = Math.max(blockL, blockW, blockH);
                    window.camera.position.set(maxDim * 1.5, maxDim * 1.5, maxDim * 1.5);
                    window.controls.target.set(blockL/2, blockH/2, blockW/2);
                    window.controls.update();
                }

                // Calculate stats
                const totalVolume = blockL * blockW * blockH;
                const totalFilled = result.filled_volume || 0;
                const stats = {
                    fillPercent: result.utilization || 0,
                    wastePercent: 100 - (result.utilization || 0),
                    totalFilled: totalFilled,
                    totalWaste: totalVolume - totalFilled,
                    totalVolume: totalVolume,
                    items: {}
                };

                if (result.item_counts) {
                    Object.keys(result.item_counts).forEach(itemId => {
                        const itemData = items.find(it => it.id == itemId);
                        const volume = itemData ? (itemData.l * itemData.w * itemData.h) : 0;
                        stats.items[itemId] = {
                            id: itemId,
                            count: result.item_counts[itemId],
                            volume: volume * result.item_counts[itemId]
                        };
                    });
                }

                // Update stats table (hidden by default, показываем таблицу заполнения)
                if (typeof window.updateStatsTable === 'function') {
                    window.updateStatsTable(items, stats, blockL, blockW, blockH);
                }

                // Simple report (ONLY percentages)
                let reportHTML = `
                    <h3>Отчет по раскладке</h3>
                    <div style="background: #fff; padding: 10px; border-radius: 3px; margin-bottom: 10px;">
                        <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                            <span><strong>Заполнение:</strong></span>
                            <span style="color: #28a745; font-weight: bold; font-size: 18px;">${stats.fillPercent.toFixed(2)}%</span>
                        </div>
                        <div style="display: flex; justify-content: space-between;">
                            <span><strong>Отходы:</strong></span>
                            <span style="color: #dc3545; font-weight: bold; font-size: 18px;">${stats.wastePercent.toFixed(2)}%</span>
                        </div>
                    </div>
                `;

                document.getElementById('result').innerHTML = reportHTML;

                // Cutting tree
                if (result.cutting_tree && typeof buildCuttingTreeHTML === 'function') {
                    const treeHTML = buildCuttingTreeHTML(result.cutting_tree);
                    if (treeHTML) {
                        document.getElementById('tree-container').innerHTML = treeHTML;
                        document.getElementById('tree-view').style.display = 'block';
                    }
                }

            } catch (error) {
                console.error('Error during optimization:', error);
                alert('Ошибка: ' + error.message);
                document.getElementById('result').innerHTML = `
                    <h3 style="color: red;">Ошибка</h3>
                    <p>${error.message}</p>
                `;
            } finally {
                runBtn.disabled = false;
                runBtn.textContent = 'Сгенерировать';
            }
        };

        console.log('App patch applied successfully');
    }

    // Init on DOMContentLoaded or immediately if already loaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPatch);
    } else {
        // Give time for app.js to initialize first
        setTimeout(initPatch, 100);
    }
})();
