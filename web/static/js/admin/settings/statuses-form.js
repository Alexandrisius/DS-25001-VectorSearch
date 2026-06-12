/**
 * Statuses add-form + save handler.
 *
 * The "add" button takes input from #newStatusId / #newStatusLabel /
 * #newStatusColor and pushes a new status. The "save" button
 * POSTs the merged statuses + default status to the server.
 *
 * Validation feedback (red border, 2-second shake) is handled via
 * the `.is-invalid` class added in the shared layer.
 *
 * Split out of the original statuses.js (239 LoC) for module size
 * management.
 */

import { state } from '../state.js';
import { authFetch } from '../../shared/api.js';
import { renderStatusesSettings } from './statuses-list.js';

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
            if (colorPreview) colorPreview.style.background = '';

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
            saveBtn.innerHTML = '<i class="fas fa-check" aria-hidden="true"></i> Сохранено!';
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
        saveBtn.innerHTML = '<i class="fas fa-times" aria-hidden="true"></i> Ошибка';
        saveBtn.classList.add('is-error');
        setTimeout(() => {
            saveBtn.innerHTML = originalText;
            saveBtn.classList.remove('is-error');
            saveBtn.disabled = false;
        }, 2000);
    }
}
