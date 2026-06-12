/**
 * LLM API (OpenRouter) display — status indicators, model labels,
 * and the "value → DOM" sync that runs after every save / test.
 *
 * updateOpenRouterUI() is the public entry-point: it reads from
 * openrouterState and paints both rows of the connection-status
 * block. updateModelDisplay() is a private helper for one row at a
 * time.
 *
 * Split out of the original openrouter.js (283 LoC) for module size
 * management.
 */

import { openrouterState } from './openrouter-state.js';

const MODEL_FIELDS = {
    Embed: {
        modelElId: 'openrouterEmbedModel',
        msgElId: 'openrouterEmbedMessage',
        indElId: 'openrouterEmbedIndicator',
    },
    Rerank: {
        modelElId: 'openrouterRerankModelText',
        msgElId: 'openrouterRerankMessage',
        indElId: 'openrouterRerankIndicator',
    },
};

/**
 * Sync every input + status indicator with the current openrouterState.
 * Called after every load/save/test.
 */
export function updateOpenRouterUI() {
    const enabledCheckbox = document.getElementById('openrouterEnabled');
    const apiKeyInput = document.getElementById('openrouterApiKey');
    const baseUrlInput = document.getElementById('openrouterBaseUrl');
    const modelEmbedInput = document.getElementById('openrouterModel');
    const modelRerankInput = document.getElementById('openrouterRerankModel');

    if (enabledCheckbox) enabledCheckbox.checked = openrouterState.enabled;
    if (apiKeyInput && openrouterState.apiKeySet) {
        apiKeyInput.placeholder = '••••••••••••••••';
    }
    if (baseUrlInput) baseUrlInput.value = openrouterState.baseUrl || '';
    if (modelEmbedInput) modelEmbedInput.value = openrouterState.modelEmbed || '';
    if (modelRerankInput) modelRerankInput.value = openrouterState.modelRerank || '';

    const batchSizeInput = document.getElementById('openrouterBatchSize');
    const maxWorkersInput = document.getElementById('openrouterMaxWorkers');
    if (batchSizeInput) batchSizeInput.value = openrouterState.batch_size || 10;
    if (maxWorkersInput) maxWorkersInput.value = openrouterState.max_workers || 3;

    updateModelDisplay('Embed', openrouterState.modelEmbed, openrouterState.embedTest);
    updateModelDisplay('Rerank', openrouterState.modelRerank, openrouterState.rerankTest);
}

/**
 * Paint a single status row (Embed or Rerank): model name, message,
 * and the coloured circle indicator.
 *
 * @param {'Embed'|'Rerank'} kind
 * @param {string} model
 * @param {{status: string, message: string}} testResult
 */
function updateModelDisplay(kind, model, testResult) {
    const isEmbed = kind === 'Embed';
    const ids = MODEL_FIELDS[kind];
    const modelEl = document.getElementById(ids.modelElId);
    const msgEl = document.getElementById(ids.msgElId);
    const indEl = document.getElementById(ids.indElId);

    if (modelEl) modelEl.textContent = model || '—';
    if (msgEl) {
        if (!openrouterState.enabled) {
            msgEl.textContent = 'Провайдер выключен';
            msgEl.className = 'status-message';
        } else if (!openrouterState.apiKeySet) {
            msgEl.textContent = 'API ключ не задан';
            msgEl.className = 'status-message';
        } else if (testResult && testResult.status && testResult.status !== 'idle') {
            msgEl.textContent = testResult.message || '';
            msgEl.className = 'status-message ' + (testResult.status === 'success' ? 'is-success' : 'is-error');
        } else {
            msgEl.textContent = 'Готов к проверке';
            msgEl.className = 'status-message';
        }
    }
    if (indEl) {
        const i = indEl.querySelector('i');
        if (!i) return;
        if (!openrouterState.enabled || !openrouterState.apiKeySet) {
            indEl.className = 'status-indicator status-inactive';
            i.className = 'fas fa-circle';
        } else if (testResult && testResult.status === 'success') {
            indEl.className = 'status-indicator status-success';
            i.className = 'fas fa-check-circle';
        } else if (testResult && testResult.status === 'error') {
            indEl.className = 'status-indicator status-error';
            i.className = 'fas fa-times-circle';
        } else {
            indEl.className = 'status-indicator status-configured';
            i.className = 'fas fa-circle';
        }
    }
}
