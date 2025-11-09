// Mode switching and DB integration for AlmaCut3D
// This file adds mode switching functionality to the main app.js

// Helper function to get item color (matching app.js logic)
function getItemColorHex(itemId, itemIndex = 0) {
    const hues = [0, 30, 60, 120, 180, 210, 240, 270, 300, 330];
    const hue = hues[itemIndex % hues.length];

    let hash = 0;
    const idStr = String(itemId);
    for (let i = 0; i < idStr.length; i++) {
        hash = idStr.charCodeAt(i) + ((hash << 5) - hash);
    }
    const hueOffset = (Math.abs(hash) % 20) - 10;

    const saturation = 75 + (Math.abs(hash) % 20);
    const lightness = 50 + (Math.abs(hash) % 15);

    return hslToHex((hue + hueOffset) / 360, saturation / 100, lightness / 100);
}

// Convert HSL to HEX
function hslToHex(h, s, l) {
    let r, g, b;

    if (s === 0) {
        r = g = b = l;
    } else {
        const hue2rgb = (p, q, t) => {
            if (t < 0) t += 1;
            if (t > 1) t -= 1;
            if (t < 1/6) return p + (q - p) * 6 * t;
            if (t < 1/2) return q;
            if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
            return p;
        };

        const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
        const p = 2 * l - q;
        r = hue2rgb(p, q, h + 1/3);
        g = hue2rgb(p, q, h);
        b = hue2rgb(p, q, h - 1/3);
    }

    const toHex = x => {
        const hex = Math.round(x * 255).toString(16);
        return hex.length === 1 ? '0' + hex : hex;
    };

    return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

// Mode switching handler
document.addEventListener('DOMContentLoaded', () => {
    const modeRadios = document.querySelectorAll('input[name="mode"]');

    modeRadios.forEach(radio => {
        radio.addEventListener('change', (e) => {
            const mode = e.target.value;

            // Hide all mode sections
            document.getElementById('manual-mode').style.display = 'none';
            document.getElementById('database-mode').style.display = 'none';
            document.getElementById('reverse-mode').style.display = 'none';

            // Show selected mode
            if (mode === 'manual') {
                document.getElementById('manual-mode').style.display = 'block';
            } else if (mode === 'database') {
                document.getElementById('database-mode').style.display = 'block';
            } else if (mode === 'reverse') {
                document.getElementById('reverse-mode').style.display = 'block';
            }
        });
    });

    // Load blocks button handler
    document.getElementById('loadBlocks').addEventListener('click', async () => {
        const material = document.getElementById('materialFilter').value;
        const url = material ? `/blocks?material=${encodeURIComponent(material)}` : '/blocks';

        try {
            const response = await fetch(url);
            const data = await response.json();

            const blocksList = document.getElementById('blocksList');
            if (!data.blocks || data.blocks.length === 0) {
                blocksList.innerHTML = '<p style="color: #999;">Нет доступных блоков</p>';
                return;
            }

            let html = '<select id="selectedBlock" style="width: 100%; padding: 5px; margin-top: 10px;">';
            html += '<option value="">-- Выберите блок --</option>';

            data.blocks.forEach(block => {
                const label = `${block.material} ${block.grade || ''} - ${block.length}×${block.width}×${block.height} мм (${block.quantity} шт.) - ${block.location}`;
                html += `<option value="${block.id}" data-l="${block.length}" data-w="${block.width}" data-h="${block.height}">${label}</option>`;
            });

            html += '</select>';
            blocksList.innerHTML = html;

            // Auto-fill block dimensions when selected
            document.getElementById('selectedBlock').addEventListener('change', (e) => {
                const option = e.target.selectedOptions[0];
                if (option.value) {
                    document.getElementById('blockL').value = option.dataset.l;
                    document.getElementById('blockW').value = option.dataset.w;
                    document.getElementById('blockH').value = option.dataset.h;
                }
            });

        } catch (error) {
            console.error('Error loading blocks:', error);
            document.getElementById('blocksList').innerHTML = '<p style="color: red;">Ошибка загрузки блоков</p>';
        }
    });
});

// Export function for updating stats table
window.updateStatsTable = function(items, stats, blockL, blockW, blockH) {
    const tbody = document.getElementById('stats-tbody');
    const totalVolume = blockL * blockW * blockH;

    let html = '';
    items.forEach((item, index) => {
        const itemStats = stats.items[item.id] || {count: 0, volume: 0};
        const volume = item.l * item.w * item.h;
        const itemPercent = (volume / totalVolume) * 100;
        const totalItemPercent = ((volume * itemStats.count) / totalVolume) * 100;

        // Get color matching 3D visualization
        const colorHex = getItemColorHex(item.id, index);

        html += `<tr>
            <td style="border: 1px solid #ddd; padding: 5px; text-align: center;">
                <div style="display: inline-block; width: 16px; height: 16px; background: ${colorHex}; border: 1px solid #999; border-radius: 3px; vertical-align: middle; margin-right: 6px;"></div>
                ${item.id}
            </td>
            <td style="border: 1px solid #ddd; padding: 5px; text-align: center;">${item.l}×${item.w}×${item.h}</td>
            <td style="border: 1px solid #ddd; padding: 5px; text-align: right;">${itemPercent.toFixed(2)}%</td>
            <td style="border: 1px solid #ddd; padding: 5px; text-align: center;">${itemStats.count}</td>
            <td style="border: 1px solid #ddd; padding: 5px; text-align: right;">${totalItemPercent.toFixed(2)}%</td>
        </tr>`;
    });

    tbody.innerHTML = html;

    // Update footer - ТОЛЬКО ПРОЦЕНТЫ
    document.getElementById('block-volume').textContent = `100%`;
    document.getElementById('filled-volume').textContent = `${stats.fillPercent.toFixed(2)}%`;
    document.getElementById('waste-volume').textContent = `${stats.wastePercent.toFixed(2)}%`;
    document.getElementById('utilization-percent').textContent = `${stats.fillPercent.toFixed(2)}%`;

    document.getElementById('stats-table').style.display = 'block';
};
