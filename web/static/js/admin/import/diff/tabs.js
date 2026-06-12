/**
 * Diff tab UI: clicked tab updates diffActiveTab and re-renders.
 */

import { diffActiveTab } from '../state.js';
import { renderDiffTable } from './render.js';

/**
 * Install delegated click handler for `.diff-tab-btn[data-tab]` buttons.
 * Called once at bootstrap.
 */
export function initDiffTabs() {
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.diff-tab-btn');
        if (!btn) return;
        const tab = btn.dataset.tab;
        if (!tab) return;
        diffActiveTab.current = tab;
        updateDiffTabUI();
        renderDiffTable();
    });
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
