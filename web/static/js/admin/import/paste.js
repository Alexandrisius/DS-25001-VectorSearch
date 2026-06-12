/**
 * "Paste" source — read textarea content, detect delimiter, parse,
 * and seed the mapping step.
 */

import { els } from '../els.js';
import { importData } from './state.js';
import { parseCSV } from './csv-parser.js';
import { renderNumberedCheckboxes, renderPreviewTable, updateAllPreviews } from './preview.js';
import { showImportStep } from './wizard.js';

/**
 * The radio input is `name="delimiter"` with values 'auto' | 'tab' | ';' | ','.
 * Default to 'tab' to match the original behaviour.
 */
export function getSelectedDelimiter() {
    const selected = document.querySelector('input[name="delimiter"]:checked');
    return selected ? selected.value : 'tab';
}

/**
 * Inspect the first line and pick the most likely delimiter.
 *
 * @param {string} text
 * @returns {string}
 */
export function detectDelimiter(text) {
    const firstLine = text.split('\n')[0] || '';
    const tabCount = (firstLine.match(/\t/g) || []).length;
    const semicolonCount = (firstLine.match(/;/g) || []).length;
    const commaCount = (firstLine.match(/,/g) || []).length;

    if (tabCount >= semicolonCount && tabCount >= commaCount && tabCount > 0) {
        return '\t';
    }
    if (semicolonCount >= commaCount && semicolonCount > 0) {
        return ';';
    }
    if (commaCount > 0) return ',';
    return '\t';
}

/**
 * Read the textarea, parse, and move to the mapping step.
 *
 * @param {string} text
 */
export function processPastedData(text) {
    const delimiterValue = getSelectedDelimiter();
    let delimiter;

    if (delimiterValue === 'auto') {
        delimiter = detectDelimiter(text);
        console.log('Авто-определён разделитель:', delimiter === '\t' ? 'Tab' : delimiter);
    } else if (delimiterValue === 'tab') {
        delimiter = '\t';
    } else {
        delimiter = delimiterValue;
    }

    const rows = parseCSV(text, delimiter);

    if (rows.length < 2) {
        alert('Недостаточно данных. Нужна минимум 1 строка заголовков и 1 строка данных.\n\nПроверьте выбранный разделитель!');
        return;
    }
    if (rows[0].length === 1) {
        alert('Обнаружена только 1 колонка. Возможно, выбран неверный разделитель.\n\nПопробуйте другой разделитель или "Авто".');
        return;
    }

    importData.headers = rows[0].map((h) => h.trim()).filter((h) => h);
    importData.raw = rows.slice(1).map((row) => {
        const obj = {};
        importData.headers.forEach((h, i) => { obj[h] = (row[i] || '').trim(); });
        return obj;
    }).filter((obj) => Object.values(obj).some((v) => v));

    // Default: only the first column is the code.
    importData.codeSelection = {};
    if (importData.headers.length > 0) {
        importData.codeSelection[importData.headers[0]] = 1;
    }
    importData.descSelection = {};
    importData.hierarchySelection = {};

    if (els.mapCodeCols) renderNumberedCheckboxes(els.mapCodeCols, importData.codeSelection, 'code');
    if (els.mapDescCols) renderNumberedCheckboxes(els.mapDescCols, importData.descSelection, 'desc');
    if (els.mapHierarchyCols) renderNumberedCheckboxes(els.mapHierarchyCols, importData.hierarchySelection, 'hierarchy');

    renderPreviewTable();
    updateAllPreviews();
    showImportStep('mapping');
}
