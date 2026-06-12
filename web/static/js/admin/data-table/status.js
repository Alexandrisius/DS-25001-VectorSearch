/**
 * Custom status dropdown for each data-table row.
 *
 * The dropdown is rendered as nested divs (not a native <select>) so
 * it can show coloured dots and a checkmark next to the selected
 * status. All interaction is delegated at the document level so
 * re-renders don't drop listeners.
 */

import { state } from '../state.js';
import { authFetch } from '../../shared/api.js';
import { escapeHtml } from '../../shared/dom.js';
import { updateRowMetaDisplay } from './render.js';

/**
 * Build the HTML for a single status dropdown cell. Used by
 * data-table/render.js when assembling a row.
 *
 * @param {string} recordId
 * @param {string} currentStatus
 * @returns {string}
 */
export function renderStatusSelect(recordId, currentStatus) {
    const currentStatusObj = state.statuses.find((s) => s.id === currentStatus);
    const statusColor = currentStatusObj ? currentStatusObj.color : '#64748b';
    const statusLabel = currentStatusObj ? currentStatusObj.label : currentStatus;

    let optionsHtml = '';
    if (state.statuses.length > 0) {
        optionsHtml = state.statuses.map((status) => {
            const isSelected = status.id === currentStatus;
            return `
                <div class="status-option ${isSelected ? 'selected' : ''}" data-value="${escapeHtml(status.id)}">
                    <span class="status-dot" style="background: ${status.color};"></span>
                    <span class="status-label">${escapeHtml(status.label)}</span>
                    <i class="fas fa-check status-check"></i>
                </div>
            `;
        }).join('');
    } else {
        // Statuses haven't loaded yet — fall back to a single option
        // showing whatever was passed in. Mirrors the previous code.
        optionsHtml = `
            <div class="status-option selected" data-value="${escapeHtml(currentStatus)}">
                <span class="status-dot" style="background: #64748b;"></span>
                <span class="status-label">${escapeHtml(currentStatus)}</span>
                <i class="fas fa-check status-check"></i>
            </div>
        `;
    }

    return `
        <div class="status-dropdown" data-id="${recordId}">
            <div class="status-dropdown-trigger" tabindex="0">
                <span class="status-dot" style="background: ${statusColor};"></span>
                <span class="status-label">${escapeHtml(statusLabel)}</span>
                <i class="fas fa-chevron-down status-arrow"></i>
            </div>
            <div class="status-dropdown-options">
                ${optionsHtml}
            </div>
        </div>
    `;
}

/**
 * Install delegated handlers for the status dropdown. Called once at
 * bootstrap — the handlers stay alive across re-renders.
 */
export function initStatusDropdowns() {
    // Close on outside click.
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.status-dropdown')) {
            document.querySelectorAll('.status-dropdown.open').forEach((dd) => {
                dd.classList.remove('open');
            });
        }
    });

    // Toggle open on trigger click.
    document.addEventListener('click', (e) => {
        const trigger = e.target.closest('.status-dropdown-trigger');
        if (!trigger) return;
        const dropdown = trigger.closest('.status-dropdown');
        const wasOpen = dropdown.classList.contains('open');

        document.querySelectorAll('.status-dropdown.open').forEach((dd) => {
            if (dd !== dropdown) dd.classList.remove('open');
        });

        dropdown.classList.toggle('open', !wasOpen);
    });

    // Option click.
    document.addEventListener('click', (e) => {
        const option = e.target.closest('.status-option');
        if (!option) return;
        const dropdown = option.closest('.status-dropdown');
        const recordId = dropdown.dataset.id;
        const newStatus = option.dataset.value;

        dropdown.classList.remove('open');

        const trigger = dropdown.querySelector('.status-dropdown-trigger');
        const statusObj = state.statuses.find((s) => s.id === newStatus);
        if (statusObj && trigger) {
            trigger.querySelector('.status-dot').style.background = statusObj.color;
            trigger.querySelector('.status-label').textContent = statusObj.label;
        }
        dropdown.querySelectorAll('.status-option').forEach((opt) => {
            opt.classList.toggle('selected', opt.dataset.value === newStatus);
        });

        handleStatusChange(recordId, newStatus);
    });
}

/**
 * PATCH a status change to the server and update local state on
 * success. On failure the dropdown is rolled back to the previous
 * value.
 *
 * @param {string} recordId
 * @param {string} newStatus
 */
export async function handleStatusChange(recordId, newStatus) {
    try {
        const res = await authFetch(
            `/admin/collections/${state.activeCollection}/data/${recordId}`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ field: 'status', value: newStatus }),
            },
        );

        if (!res.ok) throw new Error('Failed to update status');

        const result = await res.json();
        const rowData = state.dataRows.find((r) => String(r.id) === String(recordId));
        if (rowData) {
            if (!rowData.meta) rowData.meta = {};
            rowData.meta.status = newStatus;
            if (result.updated_at) {
                rowData.meta.updated_at = result.updated_at;
                rowData.meta.version = result.version;
                updateRowMetaDisplay(recordId, result.updated_at, result.version);
            }
        }
        console.log(`✅ Статус записи ${recordId} изменён на ${newStatus}`);
    } catch (e) {
        console.error('Ошибка изменения статуса:', e);
        alert('Не удалось изменить статус');

        // Roll back the dropdown to the previous value.
        const rowData = state.dataRows.find((r) => String(r.id) === String(recordId));
        if (rowData) {
            const dropdown = document.querySelector(`.status-dropdown[data-id="${recordId}"]`);
            if (dropdown) {
                const previousStatus = rowData.meta?.status || state.defaultStatus;
                const statusObj = state.statuses.find((s) => s.id === previousStatus);
                const trigger = dropdown.querySelector('.status-dropdown-trigger');
                if (trigger && statusObj) {
                    trigger.querySelector('.status-dot').style.background = statusObj.color;
                    trigger.querySelector('.status-label').textContent = statusObj.label;
                }
                dropdown.querySelectorAll('.status-option').forEach((opt) => {
                    opt.classList.toggle('selected', opt.dataset.value === previousStatus);
                });
            }
        }
    }
}
