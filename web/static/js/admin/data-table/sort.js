/**
 * Sort handler for the data table.
 *
 * Sorting is driven by clicks on `.sort-trigger` elements (the label
 * inside each <th>). We delegate from document because the table
 * header is regenerated on every render, but the triggers carry the
 * sort key as `data-sort`.
 *
 * The actual row ordering is done by renderDataTable(); this module
 * only updates state and re-asks render to redraw.
 */

import { state } from '../state.js';
import { renderDataTable } from './render.js';

/**
 * Update the sort icon (▲/▼/⇅) inside each <th> based on the current
 * sort column / direction. Re-runs on every render.
 */
export function updateSortIcons() {
    document.querySelectorAll('th.sortable').forEach((th) => {
        const icon = th.querySelector('.sort-icon');
        const column = th.dataset.sort;
        if (!icon) return;
        if (state.sortColumn === column) {
            icon.className = `fas fa-sort-${state.sortDirection === 'asc' ? 'up' : 'down'} sort-icon active`;
        } else {
            icon.className = 'fas fa-sort sort-icon';
        }
    });
}

/**
 * Wire up delegated click handler for the sort triggers. The handler
 * is installed exactly once on the document; subsequent calls are
 * no-ops (the original code's per-trigger `replaceWith` trick was
 * unnecessary once we use a single delegated listener).
 */
let sortHandlerInstalled = false;
export function initSorting() {
    if (sortHandlerInstalled) return;
    sortHandlerInstalled = true;

    document.addEventListener('click', (e) => {
        const trigger = e.target.closest('.sort-trigger');
        if (!trigger) return;
        e.stopPropagation();
        const column = trigger.dataset.sort;
        if (!column) return;

        if (state.sortColumn === column) {
            state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
        } else {
            state.sortColumn = column;
            state.sortDirection = 'asc';
        }

        updateSortIcons();
        renderDataTable();
    });
}
