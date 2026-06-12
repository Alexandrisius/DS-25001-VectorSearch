/**
 * Custom-styled <select> for picking the active database.
 *
 * Reads the options from the underlying native <select> (which is the
 * source of truth — when the server list changes, we re-build the
 * <select> and then re-render the custom UI on top of it).
 *
 * The "select database" logic lives in `database.js#setCurrentDatabase`
 * — this module only handles the click-to-select interaction and the
 * open/close UI. Delegating to the canonical implementation keeps the
 * Phase 4 metrics, db-card active state and processing-info banner
 * in sync.
 */

import { els } from './els.js';
import { setCurrentDatabase } from './database.js';

/**
 * Replace the custom dropdown with a fresh list mirroring the native
 * <select>. Called whenever the database list changes.
 */
export function initCustomSelect() {
    if (!els.customOptionsContainer) return;
    els.customOptionsContainer.innerHTML = '';

    Array.from(els.databaseSelect.options).forEach((option) => {
        const div = document.createElement('div');
        div.classList.add('custom-option');
        div.textContent = option.textContent;
        div.dataset.value = option.value;

        if (option.selected) {
            div.classList.add('selected');
            if (els.customSelectValue) els.customSelectValue.textContent = option.textContent;
        }

        div.addEventListener('click', function () {
            const wrapper = els.customSelectWrapper;
            if (!wrapper) return;
            wrapper.querySelectorAll('.custom-option').forEach((el) => el.classList.remove('selected'));
            this.classList.add('selected');
            if (els.customSelectValue) els.customSelectValue.textContent = this.textContent;
            wrapper.classList.remove('open');

            els.databaseSelect.value = this.dataset.value;
            // Delegate to the canonical setCurrentDatabase — it
            // updates Phase 4 metrics, the active db-card, the
            // processingInfo banner, and refreshes the hierarchy.
            setCurrentDatabase(this.dataset.value);
        });

        els.customOptionsContainer.appendChild(div);
    });

    // Open / close handlers (one-time setup is fine — the children
    // re-render on initCustomSelect() but the wrapper doesn't).
    setupToggleBehavior();
}

let toggleBehaviorInstalled = false;
function setupToggleBehavior() {
    if (toggleBehaviorInstalled) return;
    toggleBehaviorInstalled = true;
    const wrapper = els.customSelectWrapper;
    const trigger = els.customSelectTrigger;

    trigger?.addEventListener('click', (e) => {
        e.stopPropagation();
        wrapper.classList.toggle('open');
    });

    document.addEventListener('click', (e) => {
        if (!wrapper?.contains(e.target)) {
            wrapper.classList.remove('open');
        }
    });
}
