/**
 * LLM API (OpenRouter) settings form — load from server, save back,
 * wire the show/hide password eye-toggle and the save button.
 *
 *   - loadOpenRouterSettings:    GET on bootstrap.
 *   - initOpenRouterSettings:     one-time click wiring (save / eye).
 *   - saveOpenRouterSettings:    save button handler.
 *
 * The test button handler is in openrouter-test.js. State lives
 * in openrouter-state.js. Display in openrouter-display.js.
 *
 * Split out of the original openrouter.js (184 LoC) for module
 * size management.
 */

import { authFetch } from '../../shared/api.js';
import { openrouterState } from './openrouter-state.js';
import { updateOpenRouterUI } from './openrouter-display.js';

/**
 * Load LLM-API settings from the server. Called on bootstrap.
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

/**
 * Wire up the save / eye-toggle buttons on the LLM-API section.
 * Called once at bootstrap.
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
    // Test button is wired by openrouter-test.js to keep save/test
    // concerns in separate files.
    if (testBtn) {
        import('./openrouter-test.js').then((m) => {
            testBtn.addEventListener('click', m.testOpenRouterConnection);
        });
    }
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
