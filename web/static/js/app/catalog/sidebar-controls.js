/**
 * Catalog sidebar command buttons: refresh catalog + collapse all.
 *
 * The refresh button invalidates the server-side cache and reloads
 * the hierarchy. The collapse-all button closes every expanded
 * node and hides the sticky breadcrumbs.
 *
 * Split out of the original sidebar.js (182 LoC) for module size
 * management.
 */

import { els } from '../els.js';
import { appState, catalogState } from '../state.js';
import { loadHierarchy } from './tree.js';

/**
 * Wire up the refresh + collapse-all buttons. Called once at
 * bootstrap. The sticky-breadcrumb updater is dynamically imported
 * to keep the dependency graph one-way (breadcrumbs reads sidebar
 * state, but sidebar doesn't need to read breadcrumbs at module
 * load).
 */
export function initCatalogControls() {
    els.collapseAllBtn?.addEventListener('click', collapseAllTreeNodes);
    els.refreshCatalogBtn?.addEventListener('click', refreshCatalog);

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
