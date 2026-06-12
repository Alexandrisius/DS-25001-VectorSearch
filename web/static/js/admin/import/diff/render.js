/**
 * Diff tab UI: counter updates, badge updates, delete-warning
 * visibility, default-tab selection, and the delegated click
 * handler for tab buttons (kept here in render.js so the tables
 * file is purely a renderer with no side effects).
 *
 * Split out of the original diff/render.js (206 LoC) for module
 * size management:
 *   - render.js          (this) — orchestration + tab clicks
 *   - render-tables.js   — the actual <tr> HTML for each tab
 */

import { els } from '../../els.js';
import { diffData, diffActiveTab } from '../state.js';
import { renderDiffTable } from './render-tables.js';

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
 * Toggle the .active class on the right tab button.
 */
export function updateDiffTabUI() {
    document.querySelectorAll('.diff-tab-btn').forEach((btn) => {
        if (btn.dataset.tab === diffActiveTab.current) btn.classList.add('active');
        else btn.classList.remove('active');
    });
}

// Re-export the table renderer for the tabs handler.
export { renderDiffTable };
