/**
 * Collection config modal — Phase 4 thresholds and visibility.
 *
 * The config modal is opened by clicking the "Settings" button on a
 * collection card. Saving posts the merged payload to
 * /admin/collections/{name}/config.
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { authFetch } from '../../shared/api.js';
import { openModal, closeModal } from '../modals.js';
import { loadCollections } from './list.js';

export function initConfigForm() {
    els.saveConfigBtn?.addEventListener('click', saveConfig);
}

/**
 * Open the config modal pre-filled with the given collection's values.
 *
 * @param {string} name
 */
export function openConfigModal(name) {
    const c = state.collections.find((x) => x.name === name);
    if (!c) return;

    els.cfgName.value = c.name;
    els.cfgCosine.value = c.thresholds?.cosine ?? 0.45;
    els.cfgRerank.value = c.thresholds?.rerank ?? 0.6;
    els.cfgVisible.checked = c.visible !== undefined ? c.visible : true;

    // Phase 4: RRF + MMR + adaptive
    const p4 = c.phase4 || {};
    els.cfgRrfK.value = p4.rrf_k ?? 60;
    els.cfgMmrPool.value = p4.mmr_pool_size ?? 100;
    els.cfgRrfDense.value = p4.rrf_dense_weight ?? 1.0;
    els.cfgRrfBm25.value = p4.rrf_bm25_weight ?? 0.7;
    els.cfgMmrLambda.value = p4.mmr_lambda ?? 0.7;
    els.cfgConfidentMin.value = p4.adaptive_confident_min ?? 0.5;
    els.cfgUncertainMin.value = p4.adaptive_uncertain_min ?? 0.15;
    els.cfgFallbackCosine.value = p4.fallback_cosine_min ?? 0.30;

    openModal('config');
}

async function saveConfig() {
    const name = els.cfgName.value;
    const body = {
        visible: els.cfgVisible.checked,
        locked: false,
        thresholds: {
            cosine: parseFloat(els.cfgCosine.value),
            rerank: parseFloat(els.cfgRerank.value),
        },
        phase4: {
            rrf_k: parseInt(els.cfgRrfK.value, 10),
            mmr_pool_size: parseInt(els.cfgMmrPool.value, 10),
            rrf_dense_weight: parseFloat(els.cfgRrfDense.value),
            rrf_bm25_weight: parseFloat(els.cfgRrfBm25.value),
            mmr_lambda: parseFloat(els.cfgMmrLambda.value),
            adaptive_confident_min: parseFloat(els.cfgConfidentMin.value),
            adaptive_uncertain_min: parseFloat(els.cfgUncertainMin.value),
            fallback_cosine_min: parseFloat(els.cfgFallbackCosine.value),
        },
    };

    try {
        await authFetch(`/admin/collections/${name}/config`, {
            method: 'POST',
            body: JSON.stringify(body),
        });
        closeModal('config');
        loadCollections();
    } catch (e) {
        if (e.message !== 'Unauthorized') {
            alert('Ошибка сохранения настроек');
        }
    }
}
