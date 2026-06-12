/**
 * Data-table top-level render + sort comparator.
 *
 * renderDataTable() rebuilds the whole table from state.dataRows.
 * compareBySortKey() is the row-ordering function driven by
 * state.sortColumn / state.sortDirection.
 *
 * The header and row renderers live in their own files (render-header.js
 * and render-row.js); this module composes them and owns the sort logic.
 *
 * Split out of the original render.js (311 LoC) for module size
 * management.
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { renderDataTableHeader, extractPathLevelColumns } from './render-header.js';
import { createRowElement, updateRowMetaDisplay } from './render-row.js';
import { initInlineEdit } from './inline-edit.js';
import { initInfiniteScroll } from './scroll.js';

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

// Re-export for callers that still expect them on this module.
export { renderDataTableHeader, createRowElement, extractPathLevelColumns, updateRowMetaDisplay };
