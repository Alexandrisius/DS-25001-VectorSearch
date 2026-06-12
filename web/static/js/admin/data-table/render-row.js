/**
 * Data-table row rendering.
 *
 * createRowElement() builds a single <tr> for a record. Exposed so
 * inline-edit.js can update one cell without re-rendering the whole
 * table.
 *
 * updateRowMetaDisplay() refreshes the date/version cells of a row
 * in place after a server-side update.
 *
 * Split out of the original render.js (311 LoC) for module size
 * management.
 */

import { state } from '../state.js';
import { escapeHtml, formatDateTime } from '../../shared/dom.js';
import { renderStatusSelect } from './status.js';

/**
 * Build a <tr> element for a row. Exposed for inline-edit to use when
 * it needs to update one cell without re-rendering the whole table.
 *
 * @param {Object} row
 * @returns {HTMLTableRowElement}
 */
export function createRowElement(row) {
    const tr = document.createElement('tr');
    tr.dataset.rowId = row.id;

    const meta = row.meta || {};

    // Code (editable, centered)
    let html = `<td class="col-code editable" data-id="${row.id}" data-field="code">${escapeHtml(row.code || '')}</td>`;

    // Dynamic path-level columns.
    state.pathLevelColumns.forEach((col) => {
        const value = meta[col.key] || '';
        html += `<td class="col-hierarchy editable" data-id="${row.id}" data-field="${col.key}" title="${escapeHtml(value)}">${escapeHtml(value)}</td>`;
    });

    // Full description.
    const fullDescription = meta.full_description || row.description || '';
    html += `<td class="col-description editable" data-id="${row.id}" data-field="full_description">${escapeHtml(fullDescription)}</td>`;

    // Date (read-only).
    const updatedAt = meta.updated_at ? formatDateTime(meta.updated_at) : '—';
    html += `<td class="col-date">${updatedAt}</td>`;

    // Version (read-only).
    const version = meta.version || 1;
    html += `<td class="col-version"><span class="version-badge">v${version}</span></td>`;

    // Status.
    const currentStatus = meta.status || state.defaultStatus;
    html += `<td class="col-status">${renderStatusSelect(row.id, currentStatus)}</td>`;

    // Actions.
    html += `
        <td class="col-actions">
            <button class="btn btn-danger btn-delete-record btn-action-sm" data-id="${row.id}" title="Удалить">
                <i class="fas fa-trash"></i>
            </button>
        </td>
    `;

    tr.innerHTML = html;
    return tr;
}

/**
 * Update the date / version cells of a single row in place.
 *
 * @param {string} recordId
 * @param {string} updatedAt - ISO timestamp
 * @param {number} version
 */
export function updateRowMetaDisplay(recordId, updatedAt, version) {
    const row = document.querySelector(`tr[data-row-id="${recordId}"]`);
    if (!row) {
        console.warn(`⚠️ Строка с ID ${recordId} не найдена в DOM`);
        return;
    }
    const dateCell = row.querySelector('.col-date');
    if (dateCell) dateCell.textContent = formatDateTime(updatedAt);

    const versionCell = row.querySelector('.col-version');
    if (versionCell) versionCell.innerHTML = `<span class="version-badge">v${version}</span>`;

    console.log(`✅ Обновлено отображение: ID=${recordId}, дата=${formatDateTime(updatedAt)}, версия=v${version}`);
}
