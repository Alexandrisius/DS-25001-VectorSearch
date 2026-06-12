/**
 * Diff tab table rendering: paints the active tab (added / modified /
 * deleted) into els.diffTableBody. The Folders tab has its own
 * renderer (see render-folders.js).
 *
 * Split out of the original diff/render.js (206 LoC) for module size
 * management.
 */

import { els } from '../../els.js';
import { diffData, diffActiveTab } from '../state.js';
import { escapeHtml, truncate } from '../../../shared/dom.js';

/**
 * Render the active diff tab into els.diffTableBody. Dispatches to
 * the folders renderer when the folders tab is active.
 */
export function renderDiffTable() {
    const { added, modified, deleted, folderChanges } = diffData;

    if (diffActiveTab.current === 'folders') {
        renderFoldersDiffTable();
        return;
    }

    let data = [];
    if (diffActiveTab.current === 'added') data = added;
    else if (diffActiveTab.current === 'modified') data = modified;
    else if (diffActiveTab.current === 'deleted') data = deleted;

    if (!els.diffTableBody) return;

    if (data.length === 0) {
        els.diffTableBody.innerHTML = '';
        els.diffEmpty?.classList.remove('hidden');
        return;
    }
    els.diffEmpty?.classList.add('hidden');

    els.diffTableBody.innerHTML = data.slice(0, 100).map((record) => {
        const code = record.code || '';
        if (diffActiveTab.current === 'modified') {
            return `
                <tr>
                    <td class="code-col">${escapeHtml(code)}</td>
                    <td class="desc-col">
                        <span class="diff-old">${escapeHtml(truncate(record.oldDescription, 150))}</span>
                        <span class="diff-arrow">↓</span>
                        <span class="diff-new">${escapeHtml(truncate(record.newDescription, 150))}</span>
                    </td>
                </tr>
            `;
        } else {
            const desc = record.description || record.newDescription || '';
            return `
                <tr>
                    <td class="code-col">${escapeHtml(code)}</td>
                    <td class="desc-col">${escapeHtml(truncate(desc, 200))}</td>
                </tr>
            `;
        }
    }).join('');

    if (data.length > 100) {
        els.diffTableBody.innerHTML += `
            <tr>
                <td colspan="2" class="diff-table__overflow">... и ещё ${data.length - 100} записей</td>
            </tr>
        `;
    }
}

/**
 * Render the folders diff: three colour-coded sections (added, modified,
 * deleted), each with its own sub-header.
 */
function renderFoldersDiffTable() {
    const { folderChanges } = diffData;
    const { added, modified, deleted } = folderChanges;
    const totalChanges = added.length + modified.length + deleted.length;

    if (!els.diffTableBody) return;

    if (totalChanges === 0) {
        els.diffTableBody.innerHTML = '';
        els.diffEmpty?.classList.remove('hidden');
        return;
    }

    els.diffEmpty?.classList.add('hidden');

    let html = '';

    if (added.length > 0) {
        html += `
            <tr class="folder-section-header">
                <td colspan="3" class="diff-folder-section-header diff-folder-section-header--added">
                    <i class="fas fa-plus-circle"></i> Новые папки — ${added.length} шт.
                </td>
            </tr>
            <tr class="folder-table-subheader">
                <th class="diff-col-folder-name">Название папки</th>
                <th class="diff-col-folder-status">Статус</th>
                <th class="diff-col-folder-count">Материалов</th>
            </tr>
        `;
        added.slice(0, 50).forEach((folder) => {
            html += `
                <tr class="folder-added">
                    <td>
                        <div class="folder-name-cell">
                            <span class="folder-leaf-name">${escapeHtml(folder.leaf_name)}</span>
                            <span class="folder-full-path"><i class="fas fa-folder-open"></i> ${escapeHtml(folder.full_path)}</span>
                        </div>
                    </td>
                    <td><span class="status-badge status-new">Новая папка</span></td>
                    <td class="folder-count-cell">${folder.items_count}</td>
                </tr>
            `;
        });
        if (added.length > 50) {
            html += `<tr><td colspan="3" class="folder-more-row">... и ещё ${added.length - 50} папок</td></tr>`;
        }
    }

    if (modified.length > 0) {
        html += `
            <tr class="folder-section-header">
                <td colspan="3" class="diff-folder-section-header diff-folder-section-header--modified">
                    <i class="fas fa-pen"></i> Переименованные папки — ${modified.length} шт.
                </td>
            </tr>
            <tr class="folder-table-subheader">
                <th class="diff-col-folder-name">Новое название</th>
                <th class="diff-col-folder-status">Было</th>
                <th class="diff-col-folder-count">Материалов</th>
            </tr>
        `;
        modified.slice(0, 50).forEach((folder) => {
            html += `
                <tr class="folder-modified">
                    <td>
                        <div class="folder-name-cell">
                            <span class="folder-leaf-name">${escapeHtml(folder.leaf_name)}</span>
                            <span class="folder-full-path"><i class="fas fa-folder-open"></i> ${escapeHtml(folder.full_path)}</span>
                        </div>
                    </td>
                    <td>
                        <div class="folder-name-cell">
                            <span class="folder-leaf-name folder-leaf-name--old">${escapeHtml(folder.old_leaf_name || '')}</span>
                            <span class="folder-full-path folder-full-path--old"><i class="fas fa-folder-open"></i> ${escapeHtml(folder.old_path || '')}</span>
                        </div>
                    </td>
                    <td class="folder-count-cell">${folder.items_count}</td>
                </tr>
            `;
        });
        if (modified.length > 50) {
            html += `<tr><td colspan="3" class="folder-more-row">... и ещё ${modified.length - 50} папок</td></tr>`;
        }
    }

    if (deleted.length > 0) {
        html += `
            <tr class="folder-section-header">
                <td colspan="3" class="diff-folder-section-header diff-folder-section-header--deleted">
                    <i class="fas fa-trash-alt"></i> Удаляемые папки — ${deleted.length} шт. (нет материалов)
                </td>
            </tr>
            <tr class="folder-table-subheader">
                <th class="diff-col-folder-name">Название папки</th>
                <th class="diff-col-folder-status">Причина</th>
                <th class="diff-col-folder-count">Было мат.</th>
            </tr>
        `;
        deleted.slice(0, 50).forEach((folder) => {
            html += `
                <tr class="folder-deleted">
                    <td>
                        <div class="folder-name-cell">
                            <span class="folder-leaf-name">${escapeHtml(folder.leaf_name)}</span>
                            <span class="folder-full-path"><i class="fas fa-folder-open"></i> ${escapeHtml(folder.full_path)}</span>
                        </div>
                    </td>
                    <td><span class="status-badge status-deleted">Папка осиротела — нет материалов</span></td>
                    <td class="folder-count-cell"><span class="count-old">${folder.items_count}</span></td>
                </tr>
            `;
        });
        if (deleted.length > 50) {
            html += `<tr><td colspan="3" class="folder-more-row">... и ещё ${deleted.length - 50} папок</td></tr>`;
        }
    }

    els.diffTableBody.innerHTML = html;
}
