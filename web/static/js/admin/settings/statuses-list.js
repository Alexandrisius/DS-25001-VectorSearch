/**
 * Statuses list: load from server, render to DOM, wire color-picker
 * + remove button via delegation.
 *
 * State lives on the global admin state object (state.statuses,
 * state.defaultStatus). The add-form and save button are in
 * statuses-form.js.
 *
 * Split out of the original statuses.js (239 LoC) for module size
 * management.
 */

import { state } from '../state.js';
import { authFetch } from '../../shared/api.js';
import { escapeHtml } from '../../shared/dom.js';

const FALLBACK_STATUSES = [
    { id: 'active', label: 'Активная', color: '#10b981' },
    { id: 'draft', label: 'Черновик', color: '#f59e0b' },
    { id: 'deprecated', label: 'Устаревшая', color: '#ef4444' },
];

/**
 * Load statuses from the server. Called once during bootstrap.
 */
export async function loadStatuses() {
    try {
        const res = await fetch('/admin/statuses');
        if (res.ok) {
            const data = await res.json();
            state.statuses = data.statuses || [];
            state.defaultStatus = data.default_status || 'active';
            console.log('✅ Статусы загружены:', state.statuses.length);
        }
    } catch (e) {
        console.warn('⚠️ Не удалось загрузить статусы:', e);
        state.statuses = [...FALLBACK_STATUSES];
    }
}

/**
 * Render the statuses list and the default-status dropdown.
 */
export function renderStatusesSettings() {
    const container = document.getElementById('statusesList');
    const defaultSelect = document.getElementById('defaultStatusSelect');
    if (!container || !defaultSelect) return;

    container.innerHTML = state.statuses.map((status) => `
        <div class="status-item" data-status-id="${escapeHtml(status.id)}" style="--status-color: ${status.color};">
            <div class="status-color-preview" style="background: ${status.color};" title="Нажмите для изменения цвета">
                <i class="fas fa-palette"></i>
                <input type="color" class="status-color-picker" value="${status.color}">
            </div>
            <div class="status-content">
                <div class="status-id-badge">
                    <i class="fas fa-hashtag"></i>
                    ${escapeHtml(status.id)}
                </div>
                <input type="text" class="status-label-input" value="${escapeHtml(status.label)}" placeholder="Название статуса">
            </div>
            <button class="btn-remove-status" title="Удалить статус">
                <i class="fas fa-trash"></i>
            </button>
        </div>
    `).join('');

    defaultSelect.innerHTML = state.statuses.map((status) => `
        <option value="${escapeHtml(status.id)}" ${status.id === state.defaultStatus ? 'selected' : ''}>
            ${escapeHtml(status.label)}
        </option>
    `).join('');

    bindStatusListHandlers(container);
}

/**
 * Wire up color-picker / remove-button events on the statuses list.
 * Delegated, so it survives the list being re-rendered.
 *
 * @param {HTMLElement} container
 */
function bindStatusListHandlers(container) {
    container.addEventListener('input', (e) => {
        if (!e.target.classList.contains('status-color-picker')) return;
        const item = e.target.closest('.status-item');
        const preview = item.querySelector('.status-color-preview');
        const newColor = e.target.value;
        preview.style.background = newColor;
        item.style.setProperty('--status-color', newColor);
    });

    container.addEventListener('click', (e) => {
        const removeBtn = e.target.closest('.btn-remove-status');
        if (!removeBtn) return;
        const item = removeBtn.closest('.status-item');
        const statusId = item.dataset.statusId;

        if (statusId === state.defaultStatus) {
            alert('Нельзя удалить статус по умолчанию. Сначала выберите другой статус по умолчанию.');
            return;
        }
        if (state.statuses.length <= 1) {
            alert('Должен остаться хотя бы один статус.');
            return;
        }

        item.classList.add('is-removing');
        setTimeout(() => {
            state.statuses = state.statuses.filter((s) => s.id !== statusId);
            renderStatusesSettings();
        }, 200);
    });
}
