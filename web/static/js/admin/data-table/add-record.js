/**
 * "Add record" modal.
 *
 * Sends a record to /update_record (a public endpoint, so we use plain
 * fetch — no auth header). On success the data table is reset and
 * reloaded, and the hierarchy cache is invalidated.
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { closeModal } from '../modals.js';
import { loadData } from './scroll.js';

export function initAddRecord() {
    els.saveRecBtn?.addEventListener('click', onSave);
}

async function onSave() {
    const code = els.newRecCode.value.trim();
    const desc = els.newRecDesc.value.trim();

    if (!code || !desc) return alert('Оба поля обязательны');

    try {
        const res = await fetch('/update_record', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                code,
                description: desc,
                database: state.activeCollection,
            }),
        });

        if (res.ok) {
            try {
                await fetch(`/hierarchy/${state.activeCollection}/invalidate`, { method: 'POST' });
                console.log('✅ Кэш иерархии очищен после добавления записи');
            } catch (e) {
                console.warn('⚠️ Не удалось очистить кэш иерархии:', e);
            }

            closeModal('addRecord');
            state.dataOffset = null;
            state.dataRows = [];
            if (els.dataTableBody) els.dataTableBody.innerHTML = '';
            loadData();
        } else {
            const err = await res.json().catch(() => ({}));
            alert('Ошибка: ' + (err.detail || 'Не удалось сохранить'));
        }
    } catch (e) {
        alert('Ошибка: ' + e);
    }
}
