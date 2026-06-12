/**
 * Data-table header rendering.
 *
 * Renders the dynamic <tr> for the <thead>, including the
 * path_level_N columns that the server tells us about. Also owns
 * extractPathLevelColumns() which inspects the first row (or the
 * server-supplied max_path_depth) to figure out how many hierarchy
 * columns the table needs.
 *
 * Split out of the original render.js (311 LoC) for module size
 * management.
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { initColumnResize } from './columns-resize.js';
import { initSorting } from './sort.js';

/**
 * Render the <thead> row. Includes the dynamic path_level_N columns.
 */
export function renderDataTableHeader() {
    const thead = els.dataTableHead;
    if (!thead) return;

    let html = '<tr>';

    // Код (sortable, centered)
    html += createSortableHeader('code', 'Код', null, true);

    // Dynamic path-level columns.
    state.pathLevelColumns.forEach((col) => {
        const isActive = state.sortColumn === col.key;
        const sortIcon = isActive
            ? (state.sortDirection === 'asc' ? 'fa-sort-up' : 'fa-sort-down')
            : 'fa-sort';
        html += `
            <th class="sortable col-hierarchy-header" data-sort="${col.key}" style="min-width: 120px;">
                <div class="th-content">
                    <span class="sort-trigger" data-sort="${col.key}">
                        <i class="fas fa-folder folder-icon-inline" style="color: #f59e0b; margin-right: 5px;"></i>
                        Уровень ${col.level}
                        <i class="fas ${sortIcon} sort-icon${isActive ? ' active' : ''}"></i>
                    </span>
                </div>
            </th>
        `;
    });

    // Full description (sortable)
    const descActive = state.sortColumn === 'full_description';
    const descIcon = descActive
        ? (state.sortDirection === 'asc' ? 'fa-sort-up' : 'fa-sort-down')
        : 'fa-sort';
    html += `
        <th class="sortable col-description-th" data-sort="full_description">
            <div class="th-content">
                <span class="sort-trigger" data-sort="full_description">
                    Полное описание
                    <i class="fas ${descIcon} sort-icon${descActive ? ' active' : ''}"></i>
                </span>
            </div>
        </th>
    `;

    // Updated (sortable)
    html += createSortableHeader('updated_at', 'Изменено', 'fa-clock', true);

    // Version (read-only)
    html += `
        <th class="col-version-th">
            <div class="th-content" style="justify-content: center;">
                <i class="fas fa-code-branch th-icon-faded" style="margin-right: 5px;"></i>
                Версия
            </div>
        </th>
    `;

    // Status (read-only header)
    html += `
        <th class="col-status-th">
            <div class="th-content" style="justify-content: center;">
                <i class="fas fa-tag th-icon-faded" style="margin-right: 5px;"></i>
                Статус
            </div>
        </th>
    `;

    // Actions
    html += '<th class="col-actions-header">Действия</th>';

    html += '</tr>';
    thead.innerHTML = html;

    // Re-attach sort + resize handlers since the DOM was rebuilt.
    initSorting();
    initColumnResize();
    updateSortIcons();
}

/**
 * Helper — build a single sortable <th>.
 *
 * @param {string} sortKey
 * @param {string} label
 * @param {string|null} iconClass
 * @param {boolean} isCenter
 * @param {string} [extraClass]
 * @returns {string}
 */
function createSortableHeader(sortKey, label, iconClass, isCenter = false, extraClass = '') {
    const isActive = state.sortColumn === sortKey;
    const sortIcon = isActive
        ? (state.sortDirection === 'asc' ? 'fa-sort-up' : 'fa-sort-down')
        : 'fa-sort';
    const centerClass = isCenter ? ' col-code-th' : '';
    const iconHtml = iconClass
        ? `<i class="fas ${iconClass} th-icon-faded" style="margin-right: 5px;"></i>`
        : '';
    return `
        <th class="sortable${centerClass} ${extraClass}" data-sort="${sortKey}">
            <div class="th-content">
                <span class="sort-trigger" data-sort="${sortKey}">
                    ${iconHtml}${label}
                    <i class="fas ${sortIcon} sort-icon${isActive ? ' active' : ''}"></i>
                </span>
            </div>
        </th>
    `;
}

import { updateSortIcons } from './sort.js';

/**
 * Inspect the first record to determine how many path_level_N columns
 * the table should have. Uses server-supplied `max_path_depth` when
 * available (it represents the max across the whole collection, not
 * just the first row).
 *
 * @param {Object} row
 * @param {number} serverMaxDepth
 */
export function extractPathLevelColumns(row, serverMaxDepth = 0) {
    const meta = row.meta || {};
    const pathLevels = [];

    // serverMaxDepth first (covers the "first row is shallower than
    // the rest" edge case), fall back to per-row path_depth.
    let pathDepth = serverMaxDepth;
    if (pathDepth === 0) pathDepth = meta.path_depth || 0;

    if (pathDepth > 0) {
        for (let i = 1; i <= pathDepth; i++) {
            pathLevels.push({ key: `path_level_${i}`, level: i });
        }
    } else {
        // Fallback: scan the row for path_level_N keys.
        Object.keys(meta).forEach((key) => {
            const match = key.match(/^path_level_(\d+)$/);
            if (match) pathLevels.push({ key, level: parseInt(match[1], 10) });
        });
        pathLevels.sort((a, b) => a.level - b.level);
    }

    state.pathLevelColumns = pathLevels;
    state.hasFullDescription = 'full_description' in meta;
    console.log(`📊 Найдено ${pathLevels.length} уровней иерархии (serverMaxDepth: ${serverMaxDepth}), full_description: ${state.hasFullDescription}`);
}
