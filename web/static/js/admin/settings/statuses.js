/**
 * Settings page: record statuses.
 *
 * Statuses are stored on the server. The page maintains:
 *   - state.statuses: array of {id, label, color}
 *   - state.defaultStatus: id of the default status
 *
 * The rendered UI uses delegated event handlers and data-action
 * attributes so the HTML can be regenerated freely without losing
 * listeners.
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { authFetch } from '../../shared/api.js';
import { escapeHtml } from '../../shared/dom.js';

/**
 * Fallback statuses used when /admin/statuses is unreachable. The
 * original behaviour was to log a warning and continue; we keep that.
 */
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

    // Delegated handlers — one per concern.
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

        item.style.opacity = '0';
        item.style.transform = 'translateX(-20px)';
        setTimeout(() => {
            state.statuses = state.statuses.filter((s) => s.id !== statusId);
            renderStatusesSettings();
        }, 200);
    });
}

/**
 * Wire up the add-status and save-statuses buttons on the settings page.
 */
export function initSettingsPage() {
    const addBtn = document.getElementById('addStatusBtn');
    const saveBtn = document.getElementById('saveStatusesBtn');
    const colorInput = document.getElementById('newStatusColor');
    const colorPreview = document.getElementById('newStatusColorPreview');

    if (colorInput && colorPreview) {
        colorInput.addEventListener('input', (e) => {
            colorPreview.style.background = e.target.value;
        });
    }

    if (addBtn) {
        addBtn.addEventListener('click', () => {
            const idInput = document.getElementById('newStatusId');
            const labelInput = document.getElementById('newStatusLabel');
            const color = colorInput.value;

            const id = idInput.value.trim().toLowerCase().replace(/\s+/g, '_');
            const label = labelInput.value.trim();

            if (!id || !label) {
                if (!id) idInput.classList.add('is-invalid');
                if (!label) labelInput.classList.add('is-invalid');
                setTimeout(() => {
                    idInput.classList.remove('is-invalid');
                    labelInput.classList.remove('is-invalid');
                }, 2000);
                return;
            }

            if (state.statuses.some((s) => s.id === id)) {
                idInput.classList.add('is-invalid');
                idInput.placeholder = 'ID уже существует!';
                setTimeout(() => {
                    idInput.classList.remove('is-invalid');
                    idInput.placeholder = 'ID (review, pending...)';
                }, 2000);
                return;
            }

            state.statuses.push({ id, label, color });

            idInput.value = '';
            labelInput.value = '';
            colorInput.value = '#6366f1';
            if (colorPreview) colorPreview.style.background = '';  /* CSS default */

            renderStatusesSettings();
            idInput.focus();
        });
    }

    if (saveBtn) {
        saveBtn.addEventListener('click', saveStatusSettings);
    }
}

async function saveStatusSettings() {
    const saveBtn = document.getElementById('saveStatusesBtn');
    if (!saveBtn) return;

    const container = document.getElementById('statusesList');
    const defaultSelect = document.getElementById('defaultStatusSelect');

    const updatedStatuses = [];
    container.querySelectorAll('.status-item').forEach((item) => {
        const id = item.dataset.statusId;
        const label = item.querySelector('.status-label-input').value.trim();
        const color = item.querySelector('.status-color-picker').value;
        if (id && label) updatedStatuses.push({ id, label, color });
    });
    const defaultStatus = defaultSelect.value;

    const originalText = saveBtn.innerHTML;
    saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Сохранение...';
    saveBtn.disabled = true;

    try {
        const res = await authFetch('/admin/statuses', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                statuses: updatedStatuses,
                default_status: defaultStatus,
            }),
        });

        if (res.ok) {
            const data = await res.json();
            state.statuses = data.statuses;
            state.defaultStatus = data.default_status;
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
        console.error('Ошибка сохранения статусов:', e);
        saveBtn.innerHTML = '<i class="fas fa-times"></i> Ошибка';
        saveBtn.classList.add('is-error');
        setTimeout(() => {
            saveBtn.innerHTML = originalText;
            saveBtn.classList.remove('is-error');
            saveBtn.disabled = false;
        }, 2000);
    }
}
