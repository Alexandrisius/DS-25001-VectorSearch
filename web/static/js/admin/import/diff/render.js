/**
 * Render diff result tables and update tab UI.
 */

import { els } from '../../els.js';
import { diffData, diffActiveTab } from '../state.js';
import { escapeHtml, truncate } from '../../../shared/dom.js';
import { updateDiffTabUI } from './tabs.js';

/**
 * Update counters, badges, and the delete-warning visibility.
 */
export function updateDiffUI() {
    const { added, modified, deleted, folderChanges } = diffData;
    const totalFolderChanges =
        folderChanges.added.length + folderChanges.modified.length + folderChanges.deleted.length;

    if (els.diffAddedCount) els.diffAddedCount.textContent = added.length;
    if (els.diffModifiedCount) els.diffModifiedCount.textContent = modified.length;
    if (els.diffDeletedCount) els.diffDeletedCount.textContent = deleted.length;
    if (els.diffFoldersCount) els.diffFoldersCount.textContent = totalFolderChanges;
    if (els.diffAddedBadge) els.diffAddedBadge.textContent = added.length;
    if (els.diffModifiedBadge) els.diffModifiedBadge.textContent = modified.length;
    if (els.diffDeletedBadge) els.diffDeletedBadge.textContent = deleted.length;
    if (els.diffFoldersBadge) els.diffFoldersBadge.textContent = totalFolderChanges;

    if (deleted.length > 0) {
        els.diffDeleteWarning?.classList.remove('hidden');
    } else {
        els.diffDeleteWarning?.classList.add('hidden');
    }

    // Default the active tab to whichever has the most content.
    if (added.length > 0) diffActiveTab.current = 'added';
    else if (modified.length > 0) diffActiveTab.current = 'modified';
    else if (deleted.length > 0) diffActiveTab.current = 'deleted';
    else if (totalFolderChanges > 0) diffActiveTab.current = 'folders';
    else diffActiveTab.current = 'added';

    updateDiffTabUI();
    renderDiffTable();
}

/**
 * Render the active diff tab into els.diffTableBody. Folders go to a
 * separate renderer.
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
                <td colspan="2" style="text-align: center; color: var(--adm-text-sec); padding: 15px;">
                    ... и ещё ${data.length - 100} записей
                </td>
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
                <td colspan="3" style="background: var(--adm-success-bg); color: var(--adm-success); font-weight: 600; padding: 10px 15px;">
                    <i class="fas fa-plus-circle"></i> Новые папки — ${added.length} шт.
                </td>
            </tr>
            <tr class="folder-table-subheader">
                <th style="width: 40%;">Название папки</th>
                <th style="width: 40%;">Статус</th>
                <th style="width: 20%;">Материалов</th>
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
                <td colspan="3" style="background: #fef3c7; color: #d97706; font-weight: 600; padding: 10px 15px;">
                    <i class="fas fa-pen"></i> Переименованные папки — ${modified.length} шт.
                </td>
            </tr>
            <tr class="folder-table-subheader">
                <th style="width: 40%;">Новое название</th>
                <th style="width: 40%;">Было</th>
                <th style="width: 20%;">Материалов</th>
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
                            <span class="folder-leaf-name" style="text-decoration: line-through; opacity: 0.7;">${escapeHtml(folder.old_leaf_name || '')}</span>
                            <span class="folder-full-path" style="opacity: 0.5;"><i class="fas fa-folder-open"></i> ${escapeHtml(folder.old_path || '')}</span>
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
                <td colspan="3" style="background: var(--adm-danger-bg); color: var(--adm-danger); font-weight: 600; padding: 10px 15px;">
                    <i class="fas fa-trash-alt"></i> Удаляемые папки — ${deleted.length} шт. (нет материалов)
                </td>
            </tr>
            <tr class="folder-table-subheader">
                <th style="width: 40%;">Название папки</th>
                <th style="width: 40%;">Причина</th>
                <th style="width: 20%;">Было мат.</th>
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

