/**
 * Numbered-checkbox column-mapping UI and the live preview.
 *
 * - renderNumberedCheckboxes: rebuilds one of the three checkbox panels
 *   (code / desc / hierarchy)
 * - handleNumberedClick: assigns a sequential order to each selected
 *   column within a panel
 * - renderPreviewTable: shows the first 5 raw rows
 * - updateAllPreviews: shows the joined value the import would produce
 *   (using the first non-empty cell of each selected column)
 */

import { els } from '../els.js';
import { importData } from './state.js';

/**
 * Build a single panel.
 *
 * @param {HTMLElement} container
 * @param {Object} selection - {colName: orderNumber or 0}
 * @param {'code'|'desc'|'hierarchy'} type
 * @param {number} [defaultFirstN] - unused (kept for API compatibility)
 */
export function renderNumberedCheckboxes(container, selection, type, defaultFirstN = 0) {
    if (!container) return;
    void defaultFirstN; // preserved for API parity

    container.innerHTML = importData.headers.map((header) => {
        const order = selection[header] || 0;
        const isSelected = order > 0;
        return `
            <div class="numbered-option ${isSelected ? 'selected' : ''}"
                 data-column="${header}"
                 data-type="${type}">
                <div class="num-badge">${isSelected ? order : ''}</div>
                <span class="num-label" title="${header}">${header}</span>
            </div>
        `;
    }).join('');

    container.querySelectorAll('.numbered-option').forEach((option) => {
        option.addEventListener('click', () => handleNumberedClick(option, type));
    });
}

/**
 * Toggle a checkbox. Selecting a new column assigns the next order
 * number; deselecting renumbers the rest.
 */
export function handleNumberedClick(option, type) {
    const column = option.dataset.column;
    const selection = type === 'code' ? importData.codeSelection
        : type === 'desc' ? importData.descSelection
            : importData.hierarchySelection;

    const currentOrder = selection[column] || 0;

    if (currentOrder > 0) {
        // Deselect
        selection[column] = 0;
        Object.keys(selection).forEach((col) => {
            if (selection[col] > currentOrder) selection[col]--;
        });
    } else {
        // Select with next number
        const maxOrder = Math.max(0, ...Object.values(selection));
        selection[column] = maxOrder + 1;
    }

    const container = type === 'code' ? els.mapCodeCols
        : type === 'desc' ? els.mapDescCols
            : els.mapHierarchyCols;

    renderNumberedCheckboxes(container, selection, type);
    updateAllPreviews();
}

/**
 * First non-empty value in a column across all rows, or "Пример" if
 * the column is entirely empty.
 *
 * @param {string} columnName
 * @returns {string}
 */
export function findFirstNonEmptyValue(columnName) {
    for (const row of importData.raw) {
        const value = row[columnName];
        if (value && value.trim()) return value.trim();
    }
    return 'Пример';
}

/**
 * Update the live "this is what the joined value will look like" boxes
 * under each panel.
 */
export function updateAllPreviews() {
    if (importData.raw.length === 0) return;

    const codeSeparator = importData.codeSeparator || '.';
    const descSeparator = importData.descSeparator || ' ';

    // Code preview
    const codeCols = getOrderedSelection('code');
    const codeValue = codeCols.map((c) => findFirstNonEmptyValue(c)).join(codeSeparator);
    if (els.codePreview) {
        const codeEl = els.codePreview.querySelector('code');
        codeEl.textContent = codeValue || '—';
        codeEl.title = codeValue || '';
    }

    // Description preview
    const descCols = getOrderedSelection('desc');
    const descValue = descCols.map((c) => findFirstNonEmptyValue(c)).join(descSeparator);
    if (els.descPreview) {
        const descEl = els.descPreview.querySelector('code');
        descEl.textContent = descValue || '—';
        descEl.title = descValue || '';
    }

    // Hierarchy preview
    const hierarchyCols = getOrderedSelection('hierarchy');
    if (els.hierarchyPreview) {
        const hierarchyEl = els.hierarchyPreview.querySelector('code');
        if (hierarchyCols.length === 0) {
            const descColsInner = getOrderedSelection('desc');
            if (descColsInner.length > 0) {
                hierarchyEl.innerHTML = '<i class="fas fa-link" style="opacity:0.5; margin-right:4px;"></i>как описание';
                hierarchyEl.title = 'Будет использоваться колонка Описания';
            } else {
                hierarchyEl.textContent = '—';
                hierarchyEl.title = 'Выберите колонки описания или иерархии';
            }
        } else {
            const hierarchyValues = hierarchyCols.map((c) => findFirstNonEmptyValue(c));
            hierarchyEl.textContent = hierarchyValues.join(' / ');
            hierarchyEl.title = hierarchyValues.join(' → ');
        }
    }
}

/**
 * Render the first 5 rows of the parsed data in the preview table.
 */
export function renderPreviewTable() {
    if (!els.previewHead || !els.previewBody || !els.previewCount) return;

    els.previewHead.innerHTML = `<tr>${importData.headers.map((h) => `<th>${h}</th>`).join('')}</tr>`;

    const previewRows = importData.raw.slice(0, 5);
    els.previewBody.innerHTML = previewRows.map((row) =>
        `<tr>${importData.headers.map((h) => `<td title="${row[h] || ''}">${row[h] || '-'}</td>`).join('')}</tr>`,
    ).join('');

    els.previewCount.innerText = `${importData.raw.length} строк`;
}

/* ------------------------------------------------------------------ */
/*  Internal helpers                                                   */
/* ------------------------------------------------------------------ */

function getOrderedSelection(type) {
    const selection = type === 'code' ? importData.codeSelection
        : type === 'desc' ? importData.descSelection
            : importData.hierarchySelection;
    return Object.entries(selection)
        .filter(([, order]) => order > 0)
        .sort((a, b) => a[1] - b[1])
        .map(([col]) => col);
}
