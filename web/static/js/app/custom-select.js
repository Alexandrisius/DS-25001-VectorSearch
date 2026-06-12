/**
 * Custom-styled <select> for picking the active database.
 *
 * Reads the options from the underlying native <select> (which is the
 * source of truth — when the server list changes, we re-build the
 * <select> and then re-render the custom UI on top of it).
 */

import { els } from './els.js';
import { appState } from './state.js';

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

/**
 * Set the active database and update the custom-select UI to match.
 *
 * @param {string} name
 */
export function setCurrentDatabase(name) {
    appState.currentDatabase = name;
    if (els.databaseSelect) els.databaseSelect.value = name;

    // Re-sync the custom dropdown.
    if (els.customOptionsContainer && els.customOptionsContainer.children.length > 0) {
        const selectedOption = Array.from(els.customOptionsContainer.children)
            .find((div) => div.dataset.value === name);
        if (selectedOption) {
            if (els.customSelectValue) els.customSelectValue.textContent = selectedOption.textContent;
            Array.from(els.customOptionsContainer.children).forEach((el) => el.classList.remove('selected'));
            selectedOption.classList.add('selected');
        }
    }

    // Trigger async hierarchy refresh — deferred so the UI thread can
    // settle first (the original code used setTimeout(..., 0) for the
    // same reason).
    setTimeout(() => {
        // Lazy-import to avoid a cycle: database.js -> catalog/tree.js
        // (tree is also lazy-loaded so search.js doesn't pull it in
        // before the user is ready for it).
        import('./catalog/tree.js').then((m) => m.loadHierarchy(name));
    }, 0);

    void appState; // keep import non-pruned
}
