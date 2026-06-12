/**
 * Database list management.
 *
 *   - loadAvailableDatabases: GET /databases and seed the <select> and
 *     the db-card grid
 *   - renderDbCards: render the clickable cards under the search box
 *   - setCurrentDatabase: update the active database and refresh the
 *     catalog tree (debounced via setTimeout to free the UI thread)
 */

import { els } from './els.js';
import { appState } from './state.js';
import { initCustomSelect } from './custom-select.js';
import { loadHierarchy } from './catalog/tree.js';

/**
 * Fetch the database list and re-render the dependent UI.
 */
export async function loadAvailableDatabases() {
    try {
        const res = await fetch('/databases');
        if (res.ok) {
            const data = await res.json();
            appState.databases = data.databases;
            appState.currentDatabase = data.current_database || 'ksr_main';

            if (els.databaseSelect) {
                els.databaseSelect.innerHTML = '';
                appState.databases.forEach((db) => {
                    const opt = document.createElement('option');
                    opt.value = db.name;
                    opt.textContent = db.description.split('(')[0];
                    if (db.name === appState.currentDatabase) opt.selected = true;
                    els.databaseSelect.appendChild(opt);
                });
            }

            renderDbCards();
            initCustomSelect();
            setCurrentDatabase(appState.currentDatabase);
        }
    } catch (e) {
        console.error(e);
    }
}

/**
 * Render the clickable database cards beneath the search input.
 */
export function renderDbCards() {
    if (!els.databaseOptions) return;
    let html = '';
    appState.databases.forEach((db) => {
        const active = db.name === appState.currentDatabase ? 'active' : '';
        const dateHtml = db.last_updated
            ? `<div class="db-card-date">Обновлено: ${db.last_updated}</div>`
            : '';
        html += `
            <div class="db-card ${active}" data-name="${db.name}">
                <div class="db-card-name">${db.description.split('(')[0]}</div>
                <div class="db-card-desc">${db.record_count.toLocaleString()} записей</div>
                ${dateHtml}
            </div>`;
    });
    els.databaseOptions.innerHTML = html;
}

/**
 * Update the active database, sync the custom-select UI, and refresh
 * the catalog tree.
 *
 * @param {string} name
 */
export function setCurrentDatabase(name) {
    appState.currentDatabase = name;
    if (els.databaseSelect) els.databaseSelect.value = name;
    renderDbCards();

    // Sync the custom dropdown visual selection.
    if (els.customOptionsContainer && els.customOptionsContainer.children.length > 0) {
        const selectedOption = Array.from(els.customOptionsContainer.children)
            .find((div) => div.dataset.value === name);
        if (selectedOption) {
            if (els.customSelectValue) els.customSelectValue.textContent = selectedOption.textContent;
            Array.from(els.customOptionsContainer.children).forEach((el) => el.classList.remove('selected'));
            selectedOption.classList.add('selected');
        }
    }

    const db = appState.databases.find((d) => d.name === name);
    if (db) {
        // Phase 4: show adaptive thresholds in the metrics panel
        const p4 = db.phase4 || {};
        const confidentEl = document.getElementById('confidentMin');
        const uncertainEl = document.getElementById('uncertainMin');
        const cosineEl = document.getElementById('cosineThreshold');
        if (confidentEl) confidentEl.textContent = (p4.adaptive_confident_min ?? 0.5).toFixed(2);
        if (uncertainEl) uncertainEl.textContent = (p4.adaptive_uncertain_min ?? 0.15).toFixed(2);
        if (cosineEl) cosineEl.textContent = (p4.fallback_cosine_min ?? 0.30).toFixed(2);
        if (els.processingInfo) {
            els.processingInfo.textContent = `Выбрана база: ${db.description.split('(')[0]}`;
        }
        if (els.totalItemsEl) {
            els.totalItemsEl.textContent = db.record_count?.toLocaleString() || 0;
        }
    }

    // Defer hierarchy reload to next event loop tick so the main UI
    // stays responsive (matches the original setTimeout(..., 0) trick).
    setTimeout(() => {
        loadHierarchy(name);
    }, 0);
}
