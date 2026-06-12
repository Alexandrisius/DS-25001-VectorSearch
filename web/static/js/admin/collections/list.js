/**
 * Collections list and grid rendering.
 *
 * The grid renders one card per collection. Card action buttons use
 * `data-action` attributes; a single delegated click handler dispatches
 * to the right module (config, data-view, import, delete). This removes
 * the previous `onclick="openConfig('${name}')"` inline handlers.
 *
 * `openDataView` is the entry point for switching into the data view
 * from a collection card.
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { authFetch } from '../../shared/api.js';
import { switchView } from '../navigation.js';
import { openImport } from '../import/wizard.js';
import { openConfigModal } from './config.js';
import { confirmDeleteCollection } from './delete.js';

export async function loadCollections() {
    try {
        const res = await authFetch('/admin/collections');
        const data = await res.json();
        state.collections = data.collections;
        renderCollectionsGrid();
    } catch (e) {
        if (e.message !== 'Unauthorized') {
            console.error('Failed to load collections:', e);
        }
    }
}

function renderCollectionsGrid() {
    if (!els.collectionsGrid) return;
    els.collectionsGrid.innerHTML = '';

    state.collections.forEach((c) => {
        const isVisible = c.visible !== undefined ? c.visible : true;
        const lastUpd = c.last_updated || 'Не обновлялась';
        const recordCount = c.record_count || 0;
        const isLocked = c.locked || false;

        const card = document.createElement('div');
        card.className = 'collection-card';
        card.dataset.collectionName = c.name;
        card.innerHTML = `
            <div class="card-header">
                <div class="card-title">
                    ${isLocked ? '<i class="fas fa-lock" aria-hidden="true" title="Защищённая коллекция" style="color: var(--adm-warning); margin-right: 6px;"></i>' : ''}
                    ${c.name}
                </div>
                <span class="status-badge ${isVisible ? 'status-visible' : 'status-hidden'}">
                    ${isVisible ? '🟢 Видимая' : '🔴 Скрытая'}
                </span>
            </div>

            <p style="color:var(--adm-text-sec); font-size:0.85rem; margin-bottom:15px; flex:1">
                ${c.description || 'Без описания'}
            </p>

            <div class="card-stats">
                <div class="stat-item">
                    Записей <strong>${recordCount.toLocaleString()}</strong>
                </div>
                <div class="stat-item">
                    Обновлено <strong>${lastUpd}</strong>
                </div>
            </div>

            <div class="card-actions">
                <button class="btn btn-outline" data-action="config" data-name="${c.name}">
                    <i class="fas fa-cog" aria-hidden="true"></i> Настройки
                </button>
                <button class="btn btn-outline" data-action="data-view" data-name="${c.name}">
                    <i class="fas fa-table" aria-hidden="true"></i> Данные
                </button>
                <button class="btn btn-outline" data-action="import" data-name="${c.name}">
                    <i class="fas fa-upload" aria-hidden="true"></i> Импорт
                </button>
                <button class="btn btn-danger ${isLocked ? 'btn-locked' : ''}"
                        data-action="delete" data-name="${c.name}" data-locked="${isLocked}"
                        ${isLocked ? 'title="Защищённая коллекция"' : ''}>
                    <i class="fas fa-${isLocked ? 'lock' : 'trash'}"></i>
                </button>
            </div>
        `;
        els.collectionsGrid.appendChild(card);
    });
}

/**
 * Delegated click handler for collection cards. Installed once during
 * bootstrap.
 */
export function initCollectionsCardHandler() {
    els.collectionsGrid?.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        const action = btn.dataset.action;
        const name = btn.dataset.name;
        if (!action || !name) return;
        if (action === 'config') {
            openConfigModal(name);
        } else if (action === 'data-view') {
            openDataView(name);
        } else if (action === 'import') {
            openImport(name);
        } else if (action === 'delete') {
            confirmDeleteCollection(name, btn.dataset.locked === 'true');
        }
    });
}

/**
 * Switch into the data view for a given collection. Resets the data
 * table state and triggers the first load.
 *
 * @param {string} name
 */
export function openDataView(name) {
    state.activeCollection = name;
    switchView('data');
    state.dataOffset = null;
    state.dataRows = [];
    state.sortColumn = null;
    state.sortDirection = 'asc';
    state.pathLevelColumns = [];
    if (els.dataTableBody) els.dataTableBody.innerHTML = '';
    // Defer to data-table/scroll.js to load the first page.
    import('../data-table/scroll.js').then((m) => m.loadData());
}
