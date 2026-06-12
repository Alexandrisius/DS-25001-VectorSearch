/**
 * LLM API (OpenRouter) settings.
 *
 * The previous implementation exposed `openrouterState` as a global
 * const. We keep that pattern (renamed to `state` and scoped to this
 * module) to minimise the diff and avoid breaking call sites.
 *
 * This module never depends on the global admin `state` object; the
 * only cross-cutting concern is the authFetch helper.
 */

import { authFetch } from '../../shared/api.js';

const openrouterState = {
    enabled: false,
    apiKey: '',
    apiKeySet: false,
    baseUrl: '',
    modelEmbed: 'qwen/qwen3-embedding-4b',
    modelRerank: 'cohere/rerank-4-pro',
    batch_size: 10,
    max_workers: 3,
    embedTest: { status: 'idle', message: '' },
    rerankTest: { status: 'idle', message: '' },
};

/**
 * Load LLM-API settings from the server.
 */
export async function loadOpenRouterSettings() {
    try {
        const res = await fetch('/admin/openrouter-settings');
        if (res.ok) {
            const data = await res.json();
            openrouterState.enabled = data.enabled === true;
            openrouterState.apiKeySet = data.api_key_set === true;
            openrouterState.baseUrl = data.base_url || '';
            openrouterState.modelEmbed = data.model_embed || 'qwen/qwen3-embedding-4b';
            openrouterState.modelRerank = data.model_rerank || 'cohere/rerank-4-pro';
            openrouterState.batch_size = data.batch_size || 10;
            openrouterState.max_workers = data.max_workers || 3;

            updateOpenRouterUI();
            console.log('LLM API settings loaded:', {
                modelEmbed: openrouterState.modelEmbed,
                modelRerank: openrouterState.modelRerank,
                baseUrl: openrouterState.baseUrl,
            });
        } else {
            console.warn('Failed to load LLM settings, status:', res.status);
        }
    } catch (e) {
        console.warn('Failed to load LLM API settings:', e);
    }
}

function updateOpenRouterUI() {
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

function updateModelDisplay(kind, model, testResult) {
    const isEmbed = kind === 'Embed';
    const modelEl = document.getElementById(isEmbed ? 'openrouterEmbedModel' : 'openrouterRerankModelText');
    const msgEl = document.getElementById(isEmbed ? 'openrouterEmbedMessage' : 'openrouterRerankMessage');
    const indEl = document.getElementById(isEmbed ? 'openrouterEmbedIndicator' : 'openrouterRerankIndicator');

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

/**
 * Wire up the save / test / eye-toggle buttons on the LLM-API section.
 */
export function initOpenRouterSettings() {
    const saveBtn = document.getElementById('saveOpenrouterBtn');
    const testBtn = document.getElementById('testOpenrouterBtn');
    const toggleVisibilityBtn = document.getElementById('toggleApiKeyVisibility');
    const apiKeyInput = document.getElementById('openrouterApiKey');

    if (toggleVisibilityBtn && apiKeyInput) {
        toggleVisibilityBtn.addEventListener('click', () => {
            const type = apiKeyInput.type === 'password' ? 'text' : 'password';
            apiKeyInput.type = type;
            const icon = toggleVisibilityBtn.querySelector('i');
            if (icon) {
                icon.className = type === 'password' ? 'fas fa-eye' : 'fas fa-eye-slash';
            }
        });
    }
    saveBtn?.addEventListener('click', saveOpenRouterSettings);
    testBtn?.addEventListener('click', testOpenRouterConnection);
}

async function saveOpenRouterSettings() {
    const saveBtn = document.getElementById('saveOpenrouterBtn');
    if (!saveBtn) return;

    const enabledCheckbox = document.getElementById('openrouterEnabled');
    const apiKeyInput = document.getElementById('openrouterApiKey');
    const baseUrlInput = document.getElementById('openrouterBaseUrl');
    const modelEmbedInput = document.getElementById('openrouterModel');
    const modelRerankInput = document.getElementById('openrouterRerankModel');
    const batchSizeInput = document.getElementById('openrouterBatchSize');
    const maxWorkersInput = document.getElementById('openrouterMaxWorkers');

    const enabled = enabledCheckbox ? enabledCheckbox.checked : false;
    const apiKey = apiKeyInput ? apiKeyInput.value.trim() : '';
    const baseUrl = baseUrlInput ? baseUrlInput.value.trim() : '';
    const modelEmbed = modelEmbedInput ? modelEmbedInput.value.trim() : 'qwen/qwen3-embedding-4b';
    const modelRerank = modelRerankInput ? modelRerankInput.value.trim() : 'cohere/rerank-4-pro';
    const batch_size = batchSizeInput ? parseInt(batchSizeInput.value, 10) || 10 : 10;
    const max_workers = maxWorkersInput ? parseInt(maxWorkersInput.value, 10) || 3 : 3;

    const originalText = saveBtn.innerHTML;
    saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Сохранение...';
    saveBtn.disabled = true;

    try {
        const res = await authFetch('/admin/openrouter-settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                enabled,
                api_key: apiKey,
                base_url: baseUrl || null,
                model_embed: modelEmbed,
                model_rerank: modelRerank,
                batch_size,
                max_workers,
            }),
        });

        if (res.ok) {
            const data = await res.json();
            openrouterState.enabled = data.enabled === true;
            openrouterState.apiKeySet = data.api_key_set === true;
            openrouterState.baseUrl = data.base_url || '';
            openrouterState.modelEmbed = data.model_embed || '';
            openrouterState.modelRerank = data.model_rerank || '';
            openrouterState.batch_size = data.batch_size || 10;
            openrouterState.max_workers = data.max_workers || 3;

            if (apiKeyInput && apiKey) {
                apiKeyInput.value = '';
                apiKeyInput.placeholder = '••••••••••••••••';
            }
            updateOpenRouterUI();

            saveBtn.innerHTML = '<i class="fas fa-check"></i> Сохранено!';
            saveBtn.classList.add('is-success');
            setTimeout(() => {
                saveBtn.innerHTML = originalText;
                saveBtn.classList.remove('is-success');
                saveBtn.disabled = false;
            }, 2000);
        } else {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Не удалось сохранить');
        }
    } catch (e) {
        console.error('Ошибка сохранения настроек LLM API:', e);
        saveBtn.innerHTML = '<i class="fas fa-times"></i> Ошибка';
        saveBtn.classList.add('is-error');
        setTimeout(() => {
            saveBtn.innerHTML = originalText;
            saveBtn.classList.remove('is-error');
            saveBtn.disabled = false;
        }, 2000);
    }
}

async function testOpenRouterConnection() {
    const testBtn = document.getElementById('testOpenrouterBtn');
    if (!testBtn) return;

    const originalText = testBtn.innerHTML;
    testBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Проверка...';
    testBtn.disabled = true;

    openrouterState.embedTest = { status: 'testing', message: 'Проверка...' };
    openrouterState.rerankTest = { status: 'testing', message: 'Проверка...' };
    updateOpenRouterUI();

    try {
        const res = await authFetch('/admin/openrouter-test', { method: 'POST' });
        const data = await res.json();

        if (data.embed) {
            openrouterState.embedTest = { status: data.embed.status, message: data.embed.message || '' };
        }
        if (data.rerank) {
            openrouterState.rerankTest = { status: data.rerank.status, message: data.rerank.message || '' };
        }
        updateOpenRouterUI();

        if (data.status === 'success') {
            testBtn.innerHTML = '<i class="fas fa-check"></i> Оба OK';
            testBtn.classList.add('is-success');
        } else {
            testBtn.innerHTML = '<i class="fas fa-times"></i> Есть ошибки';
            testBtn.classList.add('is-error');
        }
        setTimeout(() => {
            testBtn.innerHTML = originalText;
            testBtn.classList.remove('is-success');
            testBtn.classList.remove('is-error');
            testBtn.disabled = false;
        }, 3000);
    } catch (e) {
        console.error('Ошибка тестирования OpenRouter:', e);
        openrouterState.embedTest = { status: 'error', message: 'Ошибка сети: ' + e.message };
        openrouterState.rerankTest = { status: 'error', message: 'Ошибка сети: ' + e.message };
        updateOpenRouterUI();

        testBtn.innerHTML = '<i class="fas fa-times"></i> Ошибка';
        testBtn.classList.add('is-error');
        setTimeout(() => {
            testBtn.innerHTML = originalText;
            testBtn.classList.remove('is-error');
            testBtn.disabled = false;
        }, 3000);
    }
}
