/**
 * Per-tree-node handlers: click, ctrl+click, long-press, copy button.
 *
 * Behaviour matrix:
 *   - click on copy icon → copy code, do not toggle
 *   - click on expand icon → toggle expand, do not select
 *   - ctrl+click → toggle multi-select, do not expand
 *   - click (no modifier) → toggle expand only (no filter)
 *   - long press (mobile) → toggle multi-select + vibrate
 */

import { filterState } from '../state.js';
import { catalogState } from './state.js';
import { toggleMultiSelect, showLongPressToast } from '../filter.js';
import { loadChildren } from './tree.js';
import { updateStickyCategoryHeader } from './breadcrumbs.js';
import { LONG_PRESS_DURATION, LONG_PRESS_MOVE_THRESHOLD } from '../../shared/constants.js';

/**
 * Toggle expand/collapse of a tree node, lazy-loading its children
 * the first time.
 */
export async function toggleTreeNodeLazy(children, expandIcon, parentPath) {
    if (children.classList.contains('collapsed')) {
        children.classList.remove('collapsed');
        children.classList.add('expanded');
        if (expandIcon) expandIcon.classList.add('expanded');
        if (!catalogState.loadedPaths.has(parentPath)) {
            await loadChildren(parentPath, children);
        }
    } else {
        children.classList.remove('expanded');
        children.classList.add('collapsed');
        if (expandIcon) expandIcon.classList.remove('expanded');
    }
    // Recompute the sticky breadcrumbs on the next tick so the DOM
    // reflects the new layout first.
    setTimeout(() => updateStickyCategoryHeader(), 100);
}

/**
 * Copy a code value to the clipboard, with a brief visual confirmation.
 */
export function copyCodeFromTree(btn) {
    const code = btn.dataset.code;
    if (!code) return;
    navigator.clipboard.writeText(code).then(() => {
        btn.classList.add('copied');
        const icon = btn.querySelector('i');
        icon?.classList.remove('fa-copy');
        icon?.classList.add('fa-check');
        setTimeout(() => {
            btn.classList.remove('copied');
            icon?.classList.remove('fa-check');
            icon?.classList.add('fa-copy');
        }, 1500);
        console.log(`📋 Скопирован код: ${code}`);
    }).catch((err) => {
        console.error('Ошибка копирования:', err);
    });
}

/**
 * Attach click / long-press / touch handlers to a single header.
 * Re-attachable safely (the headers carry their own state).
 */
export function attachSingleNodeHandler(header) {
    header.addEventListener('click', (e) => {
        if (filterState.longPressTriggered) {
            filterState.longPressTriggered = false;
            e.preventDefault();
            e.stopPropagation();
            return;
        }

        const path = header.dataset.path;
        const level = parseInt(header.dataset.level, 10);
        const node = header.closest('.tree-node');
        const children = node?.querySelector('.tree-children');
        const expandIcon = header.querySelector('.tree-node-expand');

        if (e.target.closest('.tree-node-copy')) {
            copyCodeFromTree(e.target.closest('.tree-node-copy'));
            return;
        }

        if (e.target.closest('.tree-node-expand') && children) {
            toggleTreeNodeLazy(children, expandIcon, path);
            return;
        }

        if (e.ctrlKey || e.metaKey) {
            toggleMultiSelect(path, level, header);
            return;
        }

        if (children) {
            toggleTreeNodeLazy(children, expandIcon, path);
        }
    });

    header.addEventListener('touchstart', (e) => {
        if (e.target.closest('.tree-node-copy')) return;
        const touch = e.touches[0];
        filterState.touchStartX = touch.clientX;
        filterState.touchStartY = touch.clientY;
        filterState.longPressTriggered = false;

        filterState.longPressTimer = setTimeout(() => {
            const path = header.dataset.path;
            const level = parseInt(header.dataset.level, 10);
            filterState.longPressTriggered = true;
            if (navigator.vibrate) navigator.vibrate(50);

            const wasAlreadySelected = filterState.selectedPaths.some((p) => p.path === path);
            const success = toggleMultiSelect(path, level, header);
            if (success) {
                showLongPressToast(!wasAlreadySelected);
            }
        }, LONG_PRESS_DURATION);
    }, { passive: true });

    header.addEventListener('touchmove', (e) => {
        if (!filterState.longPressTimer) return;
        const touch = e.touches[0];
        const deltaX = Math.abs(touch.clientX - filterState.touchStartX);
        const deltaY = Math.abs(touch.clientY - filterState.touchStartY);
        if (deltaX > LONG_PRESS_MOVE_THRESHOLD || deltaY > LONG_PRESS_MOVE_THRESHOLD) {
            clearTimeout(filterState.longPressTimer);
            filterState.longPressTimer = null;
        }
    }, { passive: true });

    const clearLongPress = () => {
        if (filterState.longPressTimer) {
            clearTimeout(filterState.longPressTimer);
            filterState.longPressTimer = null;
        }
    };
    header.addEventListener('touchend', clearLongPress);
    header.addEventListener('touchcancel', clearLongPress);
}

/**
 * Attach handlers to every header in a sub-tree. Used by loadChildren
 * for lazy-loaded branches.
 */
export function attachTreeEventHandlersForContainer(container) {
    container.querySelectorAll('.tree-node-header').forEach((header) => {
        attachSingleNodeHandler(header);
    });
}
