/**
 * Catalog tree DOM rendering.
 *
 *   - renderTreeLazy(): top-level paint (called after loadHierarchy).
 *   - renderTreeNodesLazy(): nested-level paint (called after loadChildren).
 *
 * Split out of tree.js for module size management.
 */

import { els } from '../els.js';
import { filterState } from '../state.js';
import { escapeHtml } from '../../shared/dom.js';

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
                <i class="fas fa-folder-open" aria-hidden="true" style="opacity: 0.5;"></i>
                <div>Категории не найдены</div>
            </div>
        `;
        return;
    }
    els.hierarchyTreeEl.innerHTML = renderTreeNodesLazy(nodes, materials);
    /* Click handlers are attached via attachTreeEventHandlers() from
       the composition root. */
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
                       <i class="fas fa-copy" aria-hidden="true"></i>
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
                            <i class="fas fa-chevron-right" aria-hidden="true"></i>
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
                       <i class="fas fa-copy" aria-hidden="true"></i>
                   </button>`
                : '';
            html += `
                <div class="tree-node material" data-code="${escapeHtml(codeValue)}">
                    <div class="tree-node-header material-item" data-code="${escapeHtml(codeValue)}">
                        <span class="tree-node-expand empty">
                            <i class="fas fa-chevron-right" aria-hidden="true" style="visibility: hidden;"></i>
                        </span>
                        <span class="tree-node-icon material">
                            <i class="fas fa-cube" aria-hidden="true"></i>
                        </span>
                        <span class="tree-node-name" title="${escapeHtml(material.name)}">${escapeHtml(material.name)}</span>
                        ${copyBtnHtml}
                    </div>
                </div>
            `;
        }
    }

    if (!html) {
        return '<div class="tree-empty-children">Нет элементов</div>';
    }
    return html;
}
