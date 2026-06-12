/**
 * Catalog tree: lazy-loaded hierarchy, node rendering, click handlers.
 *
 * The previous code had a non-lazy `renderTree(tree)` that is no
 * longer reachable from anywhere. Removed — the lazy variant covers
 * every entry point.
 */

import { els } from '../els.js';
import { appState, filterState, catalogState } from '../state.js';
import { escapeHtml } from '../../shared/dom.js';
import { clearFilter } from '../filter.js';
import { updateStickyCategoryHeader } from './breadcrumbs.js';
import {
    attachSingleNodeHandler,
    attachTreeEventHandlersForContainer,
} from './tree-handlers.js';

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
        <div class="tree-loading" style="padding: 15px;">
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
                '<div class="tree-empty-children" style="padding: 10px; color: var(--text-secondary); font-size: 0.85rem;">Нет элементов</div>';
        }
    } catch (e) {
        console.error(`❌ Ошибка загрузки детей для "${parentPath}":`, e);
        childrenContainer.innerHTML = `
            <div style="padding: 10px; color: var(--danger); font-size: 0.8rem;">
                Ошибка загрузки
            </div>
        `;
    }
}

/**
 * Render the top-level hierarchy into the tree element. Splits
 * categories and materials so the user can navigate the catalog
 * separately from the leaf-level material list.
 *
 * @param {Array} nodes - top-level categories
 * @param {Array} materials - top-level materials (no category)
 */
export function renderTreeLazy(nodes, materials = []) {
    if (!els.hierarchyTreeEl) return;
    const hasNodes = nodes && nodes.length > 0;
    const hasMaterials = materials && materials.length > 0;
    if (!hasNodes && !hasMaterials) {
        els.hierarchyTreeEl.innerHTML = `
            <div class="tree-empty">
                <i class="fas fa-folder-open" style="opacity: 0.5;"></i>
                <div>Категории не найдены</div>
            </div>
        `;
        return;
    }
    els.hierarchyTreeEl.innerHTML = renderTreeNodesLazy(nodes, materials);
    attachTreeEventHandlers();
}

/**
 * Build the HTML for a list of nodes + materials. Used both at the
 * top level (after loadHierarchy) and for nested levels (after
 * loadChildren).
 *
 * @param {Array} nodes
 * @param {Array} materials
 * @returns {string}
 */
export function renderTreeNodesLazy(nodes, materials = []) {
    let html = '';

    if (nodes && nodes.length > 0) {
        for (const node of nodes) {
            const hasChildren = node.has_children || node.has_materials
                || (node.materials && node.materials.length > 0);
            const isMultiSelected = filterState.selectedPaths.some((p) => p.path === node.path);
            const isCategory = node.is_category !== false; // default true

            const headerClasses = isMultiSelected
                ? 'tree-node-header multi-selected'
                : 'tree-node-header';

            const codeValue = node.code || (node.codes && node.codes.length > 0 ? node.codes[0] : null);
            const copyBtnHtml = codeValue
                ? `<button class="tree-node-copy" data-code="${escapeHtml(codeValue)}" title="Копировать ${escapeHtml(codeValue)}">
                       <i class="fas fa-copy"></i>
                   </button>`
                : '';

            const iconClass = isCategory
                ? (hasChildren ? 'fa-folder' : 'fa-folder-open')
                : 'fa-cube';
            const iconTypeClass = isCategory ? 'folder' : 'material';

            html += `
                <div class="tree-node ${isCategory ? 'category' : 'material'}" data-path="${escapeHtml(node.path)}" data-level="${node.level || 0}">
                    <div class="${headerClasses}" data-path="${escapeHtml(node.path)}" data-level="${node.level || 0}">
                        <span class="tree-node-expand ${hasChildren ? '' : 'empty'}">
                            <i class="fas fa-chevron-right"></i>
                        </span>
                        <span class="tree-node-icon ${iconTypeClass}">
                            <i class="fas ${iconClass}"></i>
                        </span>
                        <span class="tree-node-name" title="${escapeHtml(node.path || node.name)}">${escapeHtml(node.name)}</span>
                        ${copyBtnHtml}
                        <span class="tree-node-count">${(node.count || 1).toLocaleString()}</span>
                    </div>
                    ${hasChildren ? `
                        <div class="tree-children collapsed" data-parent-path="${escapeHtml(node.path)}">
                            <!-- Дети загружаются лениво при раскрытии -->
                        </div>
                    ` : ''}
                </div>
            `;
        }
    }

    if (materials && materials.length > 0) {
        for (const material of materials) {
            const codeValue = material.code || '';
            const copyBtnHtml = codeValue
                ? `<button class="tree-node-copy" data-code="${escapeHtml(codeValue)}" title="Копировать ${escapeHtml(codeValue)}">
                       <i class="fas fa-copy"></i>
                   </button>`
                : '';
            html += `
                <div class="tree-node material" data-code="${escapeHtml(codeValue)}">
                    <div class="tree-node-header material-item" data-code="${escapeHtml(codeValue)}">
                        <span class="tree-node-expand empty">
                            <i class="fas fa-chevron-right" style="visibility: hidden;"></i>
                        </span>
                        <span class="tree-node-icon material">
                            <i class="fas fa-cube"></i>
                        </span>
                        <span class="tree-node-name" title="${escapeHtml(material.name)}">${escapeHtml(material.name)}</span>
                        ${copyBtnHtml}
                    </div>
                </div>
            `;
        }
    }

    if (!html) {
        return '<div class="tree-empty-children" style="padding: 10px; color: var(--text-secondary); font-size: 0.85rem;">Нет элементов</div>';
    }
    return html;
}

/**
 * Attach click / long-press / touch handlers to all current tree
 * headers. Called after a render of the top-level tree.
 */
export function attachTreeEventHandlers() {
    document.querySelectorAll('.tree-node-header').forEach((header) => {
        attachSingleNodeHandler(header);
    });
}

/* silence unused (these re-exports are intentional for the
   breadcrumbs / tree-handlers modules) */
void updateStickyCategoryHeader;
