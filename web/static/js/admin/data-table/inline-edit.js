/**
 * Inline edit for data-table cells.
 *
 * Double-clicking an `.editable` cell swaps it for an <input>. Blur or
 * Enter triggers a save that PATCHes the field to the server. Cells
 * that trigger a re-embed (full_description, path_level_N) show a
 * spinner while the request is in flight.
 *
 * Editable cells are tagged with `data-bound` so we only attach one
 * listener per cell across re-renders.
 */

import { state } from '../state.js';
import { authFetch } from '../../shared/api.js';
import { escapeHtml } from '../../shared/dom.js';
import { updateRowMetaDisplay } from './render.js';

/**
 * Wire up the dblclick handler on every editable cell. Called from
 * renderDataTable() after the rows are added to the DOM.
 */
export function initInlineEdit() {
    document.querySelectorAll('.editable').forEach((td) => {
        if (td.dataset.bound) return;
        td.dataset.bound = true;

        td.addEventListener('dblclick', function () {
            if (this.classList.contains('editing')) return;

            const originalVal = this.innerText;
            const id = this.dataset.id;
            const field = this.dataset.field;
            this.classList.add('editing');

            const input = document.createElement('input');
            input.type = 'text';
            input.value = originalVal;
            this.innerHTML = '';
            this.appendChild(input);
            input.focus();

            const cellElement = this;

            const save = async () => {
                const newVal = input.value;
                if (newVal === originalVal) {
                    cellElement.innerHTML = originalVal;
                    cellElement.classList.remove('editing');
                    return;
                }

                const needsReembed = field === 'full_description'
                    || field === 'description'
                    || field.startsWith('path_level_');

                if (needsReembed) {
                    cellElement.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Пересчёт...';
                }

                try {
                    const res = await authFetch(
                        `/admin/collections/${state.activeCollection}/data/${id}`,
                        {
                            method: 'POST',
                            body: JSON.stringify({
                                code: field === 'code' ? newVal : '',
                                field,
                                value: newVal,
                            }),
                        },
                    );

                    if (res.ok) {
                        const result = await res.json();
                        cellElement.innerHTML = escapeHtml(newVal);

                        const row = state.dataRows.find((r) => String(r.id) === String(id));
                        if (row) {
                            if (field === 'code') {
                                row.code = newVal;
                            } else if (field === 'full_description') {
                                if (!row.meta) row.meta = {};
                                row.meta.full_description = newVal;
                                if (result.context_description) {
                                    row.meta.context_description = result.context_description;
                                    row.description = result.context_description;
                                }
                            } else if (field.startsWith('path_level_')) {
                                if (!row.meta) row.meta = {};
                                row.meta[field] = newVal;
                                if (result.context_description) {
                                    row.meta.context_description = result.context_description;
                                    row.description = result.context_description;
                                }
                            } else if (field === 'description') {
                                row.description = newVal;
                            }

                            if (result.updated_at) {
                                if (!row.meta) row.meta = {};
                                row.meta.updated_at = result.updated_at;
                                row.meta.version = result.version;
                                updateRowMetaDisplay(id, result.updated_at, result.version);
                            }
                        }

                        if (needsReembed && result.context_description) {
                            console.log(`✅ Эмбеддинг пересчитан для: ${result.context_description.substring(0, 50)}...`);
                        }
                    } else {
                        const err = await res.json().catch(() => ({}));
                        alert('Ошибка обновления: ' + (err.detail || 'Неизвестная ошибка'));
                        cellElement.innerHTML = escapeHtml(originalVal);
                    }
                } catch (e) {
                    if (e.message !== 'Unauthorized') {
                        alert('Ошибка обновления: ' + e.message);
                        cellElement.innerHTML = escapeHtml(originalVal);
                    }
                } finally {
                    cellElement.classList.remove('editing');
                }
            };

            input.addEventListener('blur', save);
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') input.blur();
                if (e.key === 'Escape') {
                    cellElement.innerHTML = escapeHtml(originalVal);
                    cellElement.classList.remove('editing');
                }
            });
        });
    });
}
