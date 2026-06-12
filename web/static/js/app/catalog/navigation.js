/**
 * Tree navigation: deep-link from a result, deep-link from the
 * catalog search, and the "open parent on miss" fallback.
 *
 * The "highlight pulse" on the target node uses both a CSS animation
 * and a JS safety-net timeout (5s) so it always cleans up. If the
 * browser supports the `onscrollend` event we also clean up as soon
 * as the user actually stops scrolling.
 */

import { els } from '../els.js';
import { filterState, appState } from '../state.js';
import { toggleMultiSelect, updateMultiSelectUI } from '../filter.js';
import { toggleSidebar } from './sidebar.js';
import { loadChildren } from './tree.js';
import { catalogState } from './state.js';

const HIGHLIGHT_TIMEOUT_MS = 5000;
const SCROLLEND_HOLD_MS = 1500;

/**
 * Walk down the tree, expanding every parent along `targetPath` and
 * loading its children as needed. Stops early if any link in the
 * chain is missing (returns false in that case so the caller can
 * fall back to a parent match).
 *
 * @param {string} targetPath
 * @returns {Promise<boolean>} true if every link was found
 */
export async function expandPathInTree(targetPath) {
    const separator = ' → ';
    const parts = targetPath.split(separator);
    console.log(`🔓 Раскрытие пути: "${targetPath}"`);

    let currentPath = '';
    for (let i = 0; i < parts.length - 1; i++) {
        currentPath += (i > 0 ? separator : '') + parts[i];
        const node = Array.from(document.querySelectorAll('.tree-node'))
            .find((n) => n.dataset.path === currentPath);
        if (!node) {
            console.warn(`   ⚠️ Узел "${currentPath}" не найден, прерывание цепочки`);
            return false;
        }
        const children = node.querySelector(':scope > .tree-children');
        const expandIcon = node.querySelector(':scope > .tree-node-header .tree-node-expand');
        if (children && !catalogState.loadedPaths.has(currentPath)) {
            await loadChildren(currentPath, children);
        }
        if (children && children.classList.contains('collapsed')) {
            children.classList.remove('collapsed');
            children.classList.add('expanded');
            if (expandIcon) expandIcon.classList.add('expanded');
        }
    }
    return true;
}

/**
 * Highlight a target node and scroll it into view. Returns the path
 * that was actually highlighted (or null if nothing matched).
 *
 * @param {string} categoryPath
 * @returns {string|null} the path that was highlighted, or null
 */
function highlightAndScroll(categoryPath) {
    const targetHeader = Array.from(document.querySelectorAll('.tree-node-header'))
        .find((h) => h.dataset.path === categoryPath);
    if (!targetHeader) return null;

    targetHeader.classList.add('highlight-pulse');
    targetHeader.scrollIntoView({ behavior: 'smooth', block: 'center' });

    const cleanup = () => {
        targetHeader.classList.remove('highlight-pulse');
        clearTimeout(timer);
        window.removeEventListener('scrollend', cleanup);
    };
    const timer = setTimeout(cleanup, HIGHLIGHT_TIMEOUT_MS);
    if ('onscrollend' in window) {
        const onEnd = () => {
            setTimeout(cleanup, SCROLLEND_HOLD_MS);
            window.removeEventListener('scrollend', onEnd);
        };
        setTimeout(() => window.addEventListener('scrollend', onEnd, { once: true }), 50);
    }
    return categoryPath;
}

/**
 * Click handler for a result returned by displayCatalogSearchResults.
 *
 *   - normal click  → expand & scroll to the category
 *   - Ctrl+click   → toggle multi-select, no expansion
 *
 * @param {string} path
 * @param {number} level
 * @param {MouseEvent} [event]
 */
export async function selectCategoryFromSearch(path, level, event) {
    await expandPathInTree(path);
    const targetHeader = Array.from(document.querySelectorAll('.tree-node-header'))
        .find((h) => h.dataset.path === path);

    const isCtrlClick = event && (event.ctrlKey || event.metaKey);
    if (isCtrlClick) {
        if (targetHeader) {
            toggleMultiSelect(path, level, targetHeader);
        } else {
            const exists = filterState.selectedPaths.some((p) => p.path === path);
            if (!exists) {
                filterState.selectedPaths.push({ path, level });
            } else {
                const idx = filterState.selectedPaths.findIndex((p) => p.path === path);
                if (idx > -1) filterState.selectedPaths.splice(idx, 1);
            }
            updateMultiSelectUI();
        }
    } else {
        console.log(`📍 Переход к категории: "${path}"`);
    }

    if (targetHeader) {
        // Use the shared highlight helper.
        highlightAndScroll(path);
    } else {
        console.warn(`⚠️ Целевой узел "${path}" не найден в DOM после раскрытия`);
    }
}

/**
 * Open the catalog from the search results table. The original entry
 * point for "click on a category path in the results table".
 *
 * Steps:
 *   1. Expand the sidebar if collapsed
 *   2. Expand the tree path
 *   3. Highlight the target node, or fall back to the parent
 *
 * @param {string} categoryPath
 */
export async function navigateToCategoryInCatalog(categoryPath) {
    if (!categoryPath) {
        console.warn('⚠️ Путь категории не указан');
        return;
    }
    console.log(`🔍 Навигация в каталог: "${categoryPath}"`);

    if (filterState.sidebarCollapsed) {
        toggleSidebar();
        // Wait for the open animation to settle.
        await new Promise((resolve) => setTimeout(resolve, 300));
    }

    await expandPathInTree(categoryPath);

    if (highlightAndScroll(categoryPath)) {
        console.log(`✅ Перешли к категории: "${categoryPath}"`);
        return;
    }

    // Fall back to the parent category.
    const parts = categoryPath.split(' → ');
    if (parts.length > 1) {
        const parentPath = parts.slice(0, -1).join(' → ');
        if (highlightAndScroll(parentPath)) {
            console.log(`📁 Показана родительская категория: "${parentPath}"`);
        } else {
            console.warn(`⚠️ Категория "${categoryPath}" не найдена в дереве`);
        }
    }
}

/* silence unused (appState is read in navigation to support future
   highlighting of cross-database paths) */
void appState;
