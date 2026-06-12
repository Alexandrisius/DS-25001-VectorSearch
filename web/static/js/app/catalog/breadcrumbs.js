/**
 * Sticky breadcrumbs that appear at the top of the sidebar when the
 * user scrolls past category headers. Uses requestAnimationFrame
 * for throttling and hysteresis (STICKY_HYSTERESIS) to prevent
 * flickering at boundaries.
 */

import { els } from '../els.js';
import { escapeHtml } from '../../shared/dom.js';
import { catalogState } from '../state.js';
import { STICKY_HYSTERESIS } from '../../shared/constants.js';

/**
 * Wire up the scroll listener. Installed once at bootstrap.
 */
export function initStickyCategoryHeader() {
    if (!els.sidebarContent || !els.stickyBreadcrumbs) {
        console.warn('⚠️ Элементы sticky breadcrumbs не найдены');
        return;
    }

    let rafPending = false;

    els.sidebarContent.addEventListener('scroll', () => {
        if (rafPending) return;
        rafPending = true;
        requestAnimationFrame(() => {
            rafPending = false;
            updateStickyCategoryHeader();
        });
    });
}

/**
 * Recompute the sticky-breadcrumb bar contents. Called on scroll and
 * after the tree is expanded/collapsed.
 */
export function updateStickyCategoryHeader() {
    if (!els.sidebarContent || !els.stickyBreadcrumbs) return;

    const containerRect = els.sidebarContent.getBoundingClientRect();
    const containerTop = containerRect.top;
    const stickyHeight = els.stickyBreadcrumbs.classList.contains('hidden')
        ? 0
        : els.stickyBreadcrumbs.offsetHeight;
    const baseThreshold = containerTop + stickyHeight + 10;

    const allExpandedNodes = els.sidebarContent.querySelectorAll('.tree-node > .tree-children.expanded');
    const visibleCategories = [];

    allExpandedNodes.forEach((childrenContainer) => {
        const parentNode = childrenContainer.closest('.tree-node');
        const header = parentNode?.querySelector(':scope > .tree-node-header');
        if (!header) return;
        if (!isCategoryVisible(parentNode)) return;

        const headerRect = header.getBoundingClientRect();
        const level = parseInt(header.dataset.level, 10) || 0;
        const path = header.dataset.path || '';
        const name = header.querySelector('.tree-node-name')?.textContent || '';
        const childrenRect = childrenContainer.getBoundingClientRect();

        // Hysteresis: keep a category sticky until it's fully gone.
        const isCurrentlySticky = catalogState.lastStickyPath
            && catalogState.lastStickyPath.includes(path);
        const hysteresisOffset = isCurrentlySticky ? STICKY_HYSTERESIS : 0;
        const threshold = baseThreshold - hysteresisOffset;

        if (headerRect.top < threshold
            && childrenRect.bottom > (baseThreshold + STICKY_HYSTERESIS)) {
            visibleCategories.push({ level, path, name });
        }
    });

    visibleCategories.sort((a, b) => a.level - b.level);
    const newStickyKey = visibleCategories.map((c) => c.path).join('|||');

    if (visibleCategories.length > 0) {
        if (catalogState.lastStickyPath !== newStickyKey) {
            const html = visibleCategories.map((cat) => `
                <div class="sticky-breadcrumb-item" data-level="${cat.level}" data-path="${escapeHtml(cat.path)}">
                    <i class="fas fa-folder"></i>
                    <span title="${escapeHtml(cat.path)}">${escapeHtml(cat.name)}</span>
                </div>
            `).join('');
            els.stickyBreadcrumbs.innerHTML = html;
            catalogState.lastStickyPath = newStickyKey;
        }
        els.stickyBreadcrumbs.classList.remove('hidden');
    } else {
        if (catalogState.lastStickyPath !== null) {
            els.stickyBreadcrumbs.classList.add('hidden');
            els.stickyBreadcrumbs.innerHTML = '';
            catalogState.lastStickyPath = null;
        }
    }
}

/**
 * Walk up from a node to verify every ancestor .tree-children
 * container is expanded (otherwise the node is hidden from view).
 */
export function isCategoryVisible(node) {
    let current = node.parentElement;
    while (current && !current.classList.contains('tree-view')) {
        if (current.classList.contains('tree-children')
            && current.classList.contains('collapsed')) {
            return false;
        }
        current = current.parentElement;
    }
    return true;
}
