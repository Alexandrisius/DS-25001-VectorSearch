/**
 * "Create collection" form.
 *
 * Two-step process:
 *   1. POST /create_collection with the name and dynamically-discovered
 *      embedding dimension.
 *   2. POST /admin/collections/{id}/config to attach the visible /
 *      threshold / locked metadata.
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { authFetch } from '../../shared/api.js';
import { closeModal } from '../modals.js';
import { loadCollections } from './list.js';

export function initCreateCollection() {
    els.createCollBtn?.addEventListener('click', onCreate);
}

async function onCreate() {
    const id = els.newCollId.value.trim();
    const name = els.newCollName.value.trim();
    const cosine = parseFloat(els.newCollCosine.value);
    const rerank = parseFloat(els.newCollRerank.value);
    const visible = els.newCollVisible.checked;

    if (!id) return alert('ID коллекции обязателен');

    try {
        // === Determine embedding dimension based on the current provider ===
        let dimension = 1024; // Fallback for the local model
        try {
            const dimRes = await authFetch('/admin/embedding_dimension');
            if (dimRes.ok) {
                const dimData = await dimRes.json();
                dimension = dimData.dimension;
                console.log(`📐 Размерность эмбеддингов: ${dimension} (${dimData.provider}: ${dimData.model})`);
            } else {
                console.warn('Не удалось получить размерность — используем 1024');
            }
        } catch (e) {
            console.warn('Ошибка определения размерности:', e);
        }

        const res1 = await fetch('/create_collection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                collection_name: id,
                description: name,
                dimension,
                recreate: false,
            }),
        });

        if (!res1.ok) {
            const err = await res1.json().catch(() => ({}));
            throw new Error(err.detail || 'Не удалось создать коллекцию');
        }

        const res2 = await authFetch(`/admin/collections/${id}/config`, {
            method: 'POST',
            body: JSON.stringify({
                visible,
                locked: false,
                thresholds: { cosine, rerank },
                dimension,
            }),
        });

        if (!res2.ok) console.warn('Создано, но не удалось обновить конфиг');

        closeModal('create');
        loadCollections();
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}
