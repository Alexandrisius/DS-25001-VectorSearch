/**
 * Data-table rendering: header (with dynamic path-level columns), row
 * HTML and sort-aware row ordering.
 *
 * Responsibilities:
 *   - renderDataTable: rebuilds the whole table from state.dataRows
 *   - renderDataTableHeader: builds the <tr> for the <thead>
 *   - renderRow: appends one <tr> to the <tbody>
 *   - extractPathLevelColumns: figures out how many hierarchy columns
 *     the table needs
 *
 * The original code inlined a row constructor; here we expose a
 * `createRowElement` helper so `inline-edit.js` can wrap an input
 * around an existing cell without re-rendering the whole table.
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { escapeHtml, formatDateTime } from '../../shared/dom.js';
import { initColumnResize } from './columns-resize.js';
import { initSorting, updateSortIcons } from './sort.js';
import { initInlineEdit } from './inline-edit.js';
import { initInfiniteScroll } from './scroll.js';
import { renderStatusSelect } from './status.js';

/**
 * Rebuild the entire table from state.dataRows.
 */
export function renderDataTable() {
    renderDataTableHeader();

    if (!els.dataTableBody) return;
    els.dataTableBody.innerHTML = '';

    // Apply sort if set.
    let sortedRows = [...state.dataRows];
    if (state.sortColumn) {
        sortedRows.sort(compareBySortKey);
    }

    sortedRows.forEach((row) => {
        els.dataTableBody.appendChild(createRowElement(row));
    });

    initInlineEdit();
    initInfiniteScroll();
}

/**
 * Row comparator driven by state.sortColumn / state.sortDirection.
 *
 * @param {Object} a
 * @param {Object} b
 * @returns {number}
 */
function compareBySortKey(a, b) {
    const col = state.sortColumn;
    let valA;
    let valB;

    if (col === 'code') {
        valA = a.code || '';
        valB = b.code || '';
    } else if (col === 'full_description') {
        valA = (a.meta && a.meta.full_description) || a.description || '';
        valB = (b.meta && b.meta.full_description) || b.description || '';
    } else if (col && col.startsWith('path_level_')) {
        valA = (a.meta && a.meta[col]) || '';
        valB = (b.meta && b.meta[col]) || '';
    } else if (col === 'updated_at') {
        valA = (a.meta && a.meta.updated_at) || '';
        valB = (b.meta && b.meta.updated_at) || '';
    } else if (col === 'version') {
        valA = (a.meta && a.meta.version) || 1;
        valB = (b.meta && b.meta.version) || 1;
        if (valA < valB) return state.sortDirection === 'asc' ? -1 : 1;
        if (valA > valB) return state.sortDirection === 'asc' ? 1 : -1;
        return 0;
    } else {
        valA = a[col] || '';
        valB = b[col] || '';
    }

    valA = valA.toString().toLowerCase();
    valB = valB.toString().toLowerCase();
    if (valA < valB) return state.sortDirection === 'asc' ? -1 : 1;
    if (valA > valB) return state.sortDirection === 'asc' ? 1 : -1;
    return 0;
}

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
                        <i class="fas fa-folder" style="color: #f59e0b; margin-right: 5px;"></i>
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
        <th class="sortable" data-sort="full_description" style="min-width: 300px;">
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
        <th style="min-width: 70px; text-align: center;">
            <div class="th-content" style="justify-content: center;">
                <i class="fas fa-code-branch" style="margin-right: 5px; opacity: 0.6;"></i>
                Версия
            </div>
        </th>
    `;

    // Status (read-only header)
    html += `
        <th style="min-width: 130px; text-align: center;">
            <div class="th-content" style="justify-content: center;">
                <i class="fas fa-tag" style="margin-right: 5px; opacity: 0.6;"></i>
                Статус
            </div>
        </th>
    `;

    // Actions
    html += '<th class="col-actions-header" style="width: 80px; text-align: center;">Действия</th>';

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
    const centerStyle = isCenter ? 'text-align: center;' : '';
    const iconHtml = iconClass
        ? `<i class="fas ${iconClass}" style="opacity: 0.6; margin-right: 5px;"></i>`
        : '';
    return `
        <th class="sortable ${extraClass}" data-sort="${sortKey}" style="min-width: 120px; ${centerStyle}">
            <div class="th-content">
                <span class="sort-trigger" data-sort="${sortKey}">
                    ${iconHtml}${label}
                    <i class="fas ${sortIcon} sort-icon${isActive ? ' active' : ''}"></i>
                </span>
            </div>
        </th>
    `;
}

/**
 * Build a <tr> element for a row. Exposed for inline-edit to use when
 * it needs to update one cell without re-rendering the whole table.
 *
 * @param {Object} row
 * @returns {HTMLTableRowElement}
 */
export function createRowElement(row) {
    const tr = document.createElement('tr');
    tr.dataset.rowId = row.id;

    const meta = row.meta || {};

    // Code (editable, centered)
    let html = `<td class="col-code editable" data-id="${row.id}" data-field="code">${escapeHtml(row.code || '')}</td>`;

    // Dynamic path-level columns.
    state.pathLevelColumns.forEach((col) => {
        const value = meta[col.key] || '';
        html += `<td class="col-hierarchy editable" data-id="${row.id}" data-field="${col.key}" title="${escapeHtml(value)}">${escapeHtml(value)}</td>`;
    });

    // Full description.
    const fullDescription = meta.full_description || row.description || '';
    html += `<td class="col-description editable" data-id="${row.id}" data-field="full_description">${escapeHtml(fullDescription)}</td>`;

    // Date (read-only).
    const updatedAt = meta.updated_at ? formatDateTime(meta.updated_at) : '—';
    html += `<td class="col-date">${updatedAt}</td>`;

    // Version (read-only).
    const version = meta.version || 1;
    html += `<td class="col-version"><span class="version-badge">v${version}</span></td>`;

    // Status.
    const currentStatus = meta.status || state.defaultStatus;
    html += `<td class="col-status">${renderStatusSelect(row.id, currentStatus)}</td>`;

    // Actions.
    html += `
        <td class="col-actions">
            <button class="btn btn-danger btn-delete-record" style="padding: 6px;" data-id="${row.id}" title="Удалить">
                <i class="fas fa-trash"></i>
            </button>
        </td>
    `;

    tr.innerHTML = html;
    return tr;
}

/**
 * Update the date / version cells of a single row in place.
 *
 * @param {string} recordId
 * @param {string} updatedAt - ISO timestamp
 * @param {number} version
 */
export function updateRowMetaDisplay(recordId, updatedAt, version) {
    const row = document.querySelector(`tr[data-row-id="${recordId}"]`);
    if (!row) {
        console.warn(`⚠️ Строка с ID ${recordId} не найдена в DOM`);
        return;
    }
    const dateCell = row.querySelector('.col-date');
    if (dateCell) dateCell.textContent = formatDateTime(updatedAt);

    const versionCell = row.querySelector('.col-version');
    if (versionCell) versionCell.innerHTML = `<span class="version-badge">v${version}</span>`;

    console.log(`✅ Обновлено отображение: ID=${recordId}, дата=${formatDateTime(updatedAt)}, версия=v${version}`);
}

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
