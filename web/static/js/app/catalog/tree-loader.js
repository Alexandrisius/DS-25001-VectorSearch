/**
 * Catalog tree network layer: lazy hierarchy fetch.
 *
 *   - loadHierarchy(databaseName): top-level fetch + initial render.
 *   - loadChildren(parentPath, container): child fetch + child render.
 *
 * Split out of tree.js for module size management.
 */

import { els } from '../els.js';
import { appState, catalogState } from '../state.js';
import { clearFilter } from '../filter.js';
import { renderTreeLazy, renderTreeNodesLazy } from './tree-renderer.js';
import {
    attachSingleNodeHandler,
    attachTreeEventHandlersForContainer,
} from './tree-handlers.js';

/**
 * Local helper: install click / long-press handlers on every
 * `.tree-node-header` in the current DOM. Kept here (not in the
 * renderer) so the renderer stays side-effect-free.
 */
function attachTreeEventHandlers() {
    document.querySelectorAll('.tree-node-header').forEach((header) => {
        attachSingleNodeHandler(header);
    });
}

/**
 * Load the top-level hierarchy for the current database. Subsequent
 * levels are fetched on demand when the user expands a node.
 *
 * @param {string} databaseName
 */
export async function loadHierarchy(databaseName) {
    if (!els.hierarchyTreeEl) return;
    if (catalogState.isHierarchyLoading) {
        console.log('⏳ Загрузка иерархии уже выполняется, пропускаем...');
        return;
    }

    catalogState.isHierarchyLoading = true;
    catalogState.loadedPaths.clear();

    els.hierarchyTreeEl.innerHTML = `
        <div class="tree-loading">
            <i class="fas fa-spinner fa-spin"></i>
            <div>Загрузка каталога...</div>
        </div>
    `;

    try {
        const res = await fetch(`/hierarchy/${databaseName}/children?parent_path=&level=1`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        catalogState.loadedPaths.add('');

        if (els.totalCategoriesEl) {
            els.totalCategoriesEl.textContent = data.total || 0;
        }

        renderTreeLazy(data.children || [], data.materials || []);
        attachTreeEventHandlers();
        clearFilter();
        console.log(`✅ Загружено ${data.total} элементов верхнего уровня, cached: ${data.cached}`);
    } catch (e) {
        console.error('❌ Ошибка загрузки иерархии:', e);
        if (els.hierarchyTreeEl) {
            els.hierarchyTreeEl.innerHTML = `
                <div class="tree-empty">
                    <i class="fas fa-exclamation-triangle" style="color: var(--danger);"></i>
                    <div>Не удалось загрузить каталог</div>
                    <div style="font-size: 0.8rem; margin-top: 5px;">${e.message}</div>
                </div>
            `;
        }
    } finally {
        catalogState.isHierarchyLoading = false;
    }
}

/**
 * Fetch the children of an expanded node and inject them into the
 * container element.
 *
 * @param {string} parentPath
 * @param {HTMLElement} childrenContainer
 */
export async function loadChildren(parentPath, childrenContainer) {
    if (catalogState.loadedPaths.has(parentPath)) return;

    childrenContainer.innerHTML = `
        <div class="tree-children-loading">
            <i class="fas fa-spinner fa-spin"></i>
            <span style="margin-left: 8px; font-size: 0.8rem;">Загрузка...</span>
        </div>
    `;

    try {
        const res = await fetch(
            `/hierarchy/${appState.currentDatabase}/children?parent_path=${encodeURIComponent(parentPath)}`,
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        catalogState.loadedPaths.add(parentPath);

        const hasChildren = (data.children && data.children.length > 0);
        const hasMaterials = (data.materials && data.materials.length > 0);

        if (hasChildren || hasMaterials) {
            childrenContainer.innerHTML = renderTreeNodesLazy(data.children || [], data.materials || []);
            attachTreeEventHandlersForContainer(childrenContainer);
        } else {
            childrenContainer.innerHTML =
                '<div class="tree-empty-children">Нет элементов</div>';
        }
    } catch (e) {
        console.error(`❌ Ошибка загрузки детей для "${parentPath}":`, e);
        childrenContainer.innerHTML = `
            <div class="tree-error">
                Ошибка загрузки
            </div>
        `;
    }
}
