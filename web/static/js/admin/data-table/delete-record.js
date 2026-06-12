/**
 * "Delete record" from the data table.
 *
 * The delete button uses `data-id="<uuid>"` — a delegated click
 * handler on document catches it. The handler is installed once at
 * bootstrap, so re-renders don't lose it (the previous code attached
 * the listener at the top of admin.js, which also worked but mixed
 * init with logic).
 */

import { state } from '../state.js';
import { els } from '../els.js';

/**
 * Install the document-level click handler. Called from main.js.
 */
export function initDeleteRecordDelegation() {
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.btn-delete-record');
        if (!btn) return;
        const id = btn.dataset.id;
        if (id) deleteRecord(id);
    });
}

/**
 * Delete a record by id. Confirms with the user, DELETEs the record,
 * invalidates the hierarchy cache, removes the row from state and
 * the DOM.
 *
 * @param {string} id
 */
export async function deleteRecord(id) {
    const collection = state.collections.find((c) => c.name === state.activeCollection);
    if (collection && collection.locked) {
        alert('🔒 Невозможно удалить запись - коллекция защищена.\n\nДля снятия защиты измените locked: false в настройках.');
        return;
    }

    if (!confirm('Вы уверены, что хотите удалить эту запись?')) return;

    try {
        console.log(`🗑️ Удаление записи с ID: ${id} из коллекции ${state.activeCollection}`);

        const { authFetch } = await import('../../shared/api.js');
        const res = await authFetch(`/admin/collections/${state.activeCollection}/data/${id}`, {
            method: 'DELETE',
        });

        if (!res.ok) {
            const errorData = await res.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP ${res.status}`);
        }

        console.log(`✅ Запись ${id} успешно удалена на сервере`);

        try {
            await fetch(`/hierarchy/${state.activeCollection}/invalidate`, { method: 'POST' });
            console.log('✅ Кэш иерархии очищен после удаления записи');
        } catch (e) {
            console.warn('⚠️ Не удалось очистить кэш иерархии:', e);
        }

        state.dataRows = state.dataRows.filter((r) => String(r.id) !== String(id));

        const tr = document.querySelector(`tr[data-row-id="${id}"]`);
        if (tr) {
            tr.remove();
        } else {
            // Reload if the row wasn't in the DOM (e.g. not on the
            // current page).
            state.dataOffset = null;
            state.dataRows = [];
            if (els.dataTableBody) els.dataTableBody.innerHTML = '';
            const { loadData } = await import('./scroll.js');
            loadData();
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') {
            console.error('❌ Ошибка удаления записи:', e);
            alert('Ошибка удаления: ' + e.message);
        }
    }
}
