/**
 * Catalog sidebar: toggle, resize, refresh button, collapse-all.
 */

import { els } from '../els.js';
import { appState, filterState, catalogState } from '../state.js';
import { STORAGE_KEYS } from '../../shared/constants.js';
import { loadHierarchy } from './tree.js';
import { clearAllSelections } from '../filter.js';

/**
 * Wire up sidebar controls. Called once at bootstrap.
 */
export function initCatalogSidebar() {
    if (!els.catalogSidebar || !els.sidebarToggle) {
        console.warn('⚠️ Элементы sidebar не найдены');
        return;
    }

    els.sidebarToggle.addEventListener('click', toggleSidebar);
    initSidebarResizer();
    initStickyHeader();

    els.clearSelectionBtn?.addEventListener('click', clearAllSelections);

    els.collapseAllBtn?.addEventListener('click', collapseAllTreeNodes);
    els.refreshCatalogBtn?.addEventListener('click', refreshCatalog);

    // Restore collapsed state.
    let saved = 'false';
    try {
        saved = localStorage.getItem(STORAGE_KEYS.catalogSidebarCollapsed) || 'false';
    } catch {
        saved = 'false';
    }
    if (saved === 'true') {
        filterState.sidebarCollapsed = true;
        els.catalogSidebar.classList.add('collapsed');
        els.appLayout?.classList.remove('sidebar-open');
        els.appLayout?.classList.add('sidebar-collapsed');
        updateToggleButton();
    } else {
        applySidebarWidth();
    }
}

/**
 * Toggle the sidebar open / closed and persist the new state.
 */
export function toggleSidebar() {
    filterState.sidebarCollapsed = !filterState.sidebarCollapsed;
    els.catalogSidebar.classList.toggle('collapsed', filterState.sidebarCollapsed);

    if (filterState.sidebarCollapsed) {
        els.appLayout?.classList.remove('sidebar-open');
        els.appLayout?.classList.add('sidebar-collapsed');
        els.catalogSidebar.style.width = '';
    } else {
        els.appLayout?.classList.remove('sidebar-collapsed');
        els.appLayout?.classList.add('sidebar-open');
        applySidebarWidth();
    }
    updateToggleButton();
    try {
        localStorage.setItem(STORAGE_KEYS.catalogSidebarCollapsed, String(filterState.sidebarCollapsed));
    } catch {
        /* storage unavailable */
    }
}

/**
 * Initialise the drag-resize handle for the sidebar.
 */
function initSidebarResizer() {
    if (!els.sidebarResizer) return;

    let isResizing = false;
    let startX = 0;
    let startWidth = 0;

    els.sidebarResizer.addEventListener('mousedown', (e) => {
        isResizing = true;
        startX = e.clientX;
        startWidth = els.catalogSidebar.offsetWidth;
        els.sidebarResizer.classList.add('active');
        document.body.style.cursor = 'ew-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const delta = e.clientX - startX;
        const newWidth = Math.max(350, Math.min(800, startWidth + delta));
        filterState.sidebarWidth = newWidth;
        applySidebarWidth();
    });

    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            els.sidebarResizer.classList.remove('active');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            try {
                localStorage.setItem(STORAGE_KEYS.sidebarWidth, String(filterState.sidebarWidth));
            } catch {
                /* storage unavailable */
            }
        }
    });
}

/**
 * Apply the saved width to the sidebar element and to the
 * `--sidebar-width` CSS custom property.
 */
export function applySidebarWidth() {
    if (filterState.sidebarCollapsed) return;
    if (els.catalogSidebar) {
        els.catalogSidebar.style.width = filterState.sidebarWidth + 'px';
    }
    document.documentElement.style.setProperty('--sidebar-width', filterState.sidebarWidth + 'px');
}

/**
 * Update the toggle button's icon and text to reflect the current
 * collapse state.
 */
export function updateToggleButton() {
    if (!els.sidebarToggle) return;
    const icon = els.sidebarToggle.querySelector('i');
    const text = els.sidebarToggle.querySelector('.toggle-text');
    if (filterState.sidebarCollapsed) {
        icon?.classList.remove('fa-angles-left');
        icon?.classList.add('fa-angles-right');
        if (text) text.textContent = 'Развернуть';
    } else {
        icon?.classList.remove('fa-angles-right');
        icon?.classList.add('fa-angles-left');
        if (text) text.textContent = 'Свернуть';
    }
}

/**
 * Init the scroll-driven sticky breadcrumbs updater. Done via dynamic
 * import to keep this file's dependency graph one-way (breadcrumbs
 * reads sidebar state, but sidebar doesn't need to read breadcrumbs
 * at module load).
 */
function initStickyHeader() {
    import('./breadcrumbs.js').then((m) => m.initStickyCategoryHeader());
}

/**
 * Collapse every expanded node in the tree.
 */
export function collapseAllTreeNodes() {
    const expanded = document.querySelectorAll('.tree-children.expanded');
    expanded.forEach((children) => {
        children.classList.remove('expanded');
        children.classList.add('collapsed');
        const parentNode = children.closest('.tree-node');
        if (parentNode) {
            const expandIcon = parentNode.querySelector(':scope > .tree-node-header .tree-node-expand');
            expandIcon?.classList.remove('expanded');
        }
    });
    els.stickyBreadcrumbs?.classList.add('hidden');
    if (els.stickyBreadcrumbs) els.stickyBreadcrumbs.innerHTML = '';
    catalogState.lastStickyPath = null;
    console.log(`📁 Свёрнуто ${expanded.length} категорий`);
}

/**
 * Invalidate the server-side cache and re-load the hierarchy.
 * Triggered by the "Refresh" button.
 */
export async function refreshCatalog() {
    const refreshBtn = els.refreshCatalogBtn;
    const icon = refreshBtn ? refreshBtn.querySelector('i') : null;

    if (icon) icon.classList.add('fa-spin');
    if (refreshBtn) refreshBtn.disabled = true;

    try {
        console.log(`🔄 Инвалидация кэша для ${appState.currentDatabase}...`);
        const res = await fetch(`/hierarchy/${appState.currentDatabase}/invalidate`, { method: 'POST' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        console.log('✅ Серверный кэш очищен');
        catalogState.loadedPaths.clear();
        collapseAllTreeNodes();
        await loadHierarchy(appState.currentDatabase);
        console.log('✅ Каталог обновлён');
    } catch (e) {
        console.error('❌ Ошибка обновления каталога:', e);
        alert('Ошибка обновления каталога: ' + e.message);
    } finally {
        if (icon) icon.classList.remove('fa-spin');
        if (refreshBtn) refreshBtn.disabled = false;
    }
}
