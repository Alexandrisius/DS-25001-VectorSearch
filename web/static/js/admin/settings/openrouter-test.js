/**
 * LLM API connection test: pings /admin/openrouter-test, updates the
 * two status rows (embed + rerank) and flashes a state class on
 * the test button.
 *
 * Split out of openrouter.js (184 LoC) for module size management.
 */

import { authFetch } from '../../shared/api.js';
import { openrouterState } from './openrouter-state.js';
import { updateOpenRouterUI } from './openrouter-display.js';

export async function testOpenRouterConnection() {
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
