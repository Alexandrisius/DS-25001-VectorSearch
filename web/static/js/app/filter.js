/**
 * Category multi-select filter logic.
 *
 *   - toggleMultiSelect:   add or remove a category from the filter
 *   - clearAllSelections:  drop every selected path
 *   - clearFilter:         full reset (paths, current path/level, UI)
 *   - updateMultiSelectUI: refresh the multi-select banner + indicator
 *   - showCategoryOnlyToast: "you can only filter by category" toast
 *   - showLongPressToast:  feedback when long-press toggles a selection
 */

import { els } from './els.js';
import { filterState } from './state.js';

/**
 * Toggle a path in the multi-select. Returns true on success, false if
 * the node was a leaf (materials can't be filtered).
 *
 * @param {string} path
 * @param {number} level
 * @param {HTMLElement} header
 * @returns {boolean}
 */
export function toggleMultiSelect(path, level, header) {
    const idx = filterState.selectedPaths.findIndex((p) => p.path === path);
    if (idx > -1) {
        filterState.selectedPaths.splice(idx, 1);
        header.classList.remove('multi-selected');
        updateMultiSelectUI();
        return true;
    }
    // Only folders (categories) can be selected; leaves (materials) cannot.
    const node = header.closest('.tree-node');
    const hasChildren = node && node.querySelector('.tree-children');
    if (!hasChildren) {
        showCategoryOnlyToast();
        return false;
    }
    filterState.selectedPaths.push({ path, level });
    header.classList.add('multi-selected');
    updateMultiSelectUI();
    return true;
}

/**
 * Drop every selected path and refresh the UI.
 */
export function clearAllSelections() {
    filterState.selectedPaths = [];
    document.querySelectorAll('.tree-node-header.multi-selected').forEach((h) => {
        h.classList.remove('multi-selected');
    });
    updateMultiSelectUI();
}

/**
 * Full filter reset (paths + current path/level + UI banners).
 */
export function clearFilter() {
    filterState.currentFilterPath = null;
    filterState.currentFilterLevel = null;
    filterState.selectedPaths = [];

    document.querySelectorAll('.tree-node-header.multi-selected').forEach((h) => {
        h.classList.remove('multi-selected');
    });
    els.multiSelectHint?.classList.add('hidden');
    els.filterIndicator?.classList.remove('active');

    if (els.processingInfo) {
        els.processingInfo.textContent = 'Ожидание запроса...';
    }

    console.log('🔍 Фильтр сброшен');
}

/**
 * Refresh the multi-select banner and the sidebar filter indicator.
 */
export function updateMultiSelectUI() {
    if (filterState.selectedPaths.length > 0) {
        els.multiSelectHint?.classList.remove('hidden');
        if (els.selectedCountEl) {
            els.selectedCountEl.textContent = filterState.selectedPaths.length;
        }
        const pathNames = filterState.selectedPaths
            .map((p) => p.path.split(' → ').pop())
            .join(', ');
        if (els.processingInfo) {
            els.processingInfo.textContent = `Фильтр: ${pathNames}`;
        }
        filterState.currentFilterPath = filterState.selectedPaths[0].path;
        filterState.currentFilterLevel = filterState.selectedPaths[0].level;
        els.filterIndicator?.classList.add('active');
    } else {
        els.multiSelectHint?.classList.add('hidden');
        els.filterIndicator?.classList.remove('active');
        filterState.currentFilterPath = null;
        filterState.currentFilterLevel = null;
        if (els.processingInfo) {
            els.processingInfo.textContent = 'Ожидание запроса...';
        }
    }
}

/**
 * Toast: "you can only filter by categories, not materials".
 */
export function showCategoryOnlyToast() {
    removeExistingToast();
    const toast = document.createElement('div');
    toast.className = 'longpress-toast toast-warning';
    toast.innerHTML = '<i class="fas fa-exclamation-triangle" aria-hidden="true"></i> Можно выбрать только категории';
    document.body.appendChild(toast);
    scheduleToastRemoval(toast);
}

/**
 * Toast: feedback after a long-press toggled a selection.
 *
 * @param {boolean} added - true if the category was added
 */
export function showLongPressToast(added) {
    removeExistingToast();
    const toast = document.createElement('div');
    toast.className = 'longpress-toast';
    toast.innerHTML = added
        ? '<i class="fas fa-check" aria-hidden="true"></i> Добавлено в фильтр'
        : '<i class="fas fa-times" aria-hidden="true"></i> Удалено из фильтра';
    document.body.appendChild(toast);
    scheduleToastRemoval(toast);
}

function removeExistingToast() {
    const existing = document.querySelector('.longpress-toast');
    if (existing) existing.remove();
}

function scheduleToastRemoval(toast) {
    setTimeout(() => {
        toast.classList.add('fade-out');
        setTimeout(() => toast.remove(), 300);
    }, 2000);
}
