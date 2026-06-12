/**
 * Validation and helpers for the column-mapping step.
 */

import { importData } from './state.js';
import { stripSymmetricQuotes } from './csv-parser.js';
import { applyCleaningRules } from '../cleaning-rules/apply.js';

/**
 * Make sure the user has selected at least one column for code and
 * description. Returns true on success; false on failure (after
 * showing an alert).
 */
export function validateMapping() {
    const codeCols = getOrderedSelection('code');
    const descCols = getOrderedSelection('desc');

    if (codeCols.length === 0) {
        alert('Выберите хотя бы одну колонку для Кода (ID).');
        return false;
    }
    if (descCols.length === 0) {
        alert('Выберите хотя бы одну колонку для Описания.');
        return false;
    }
    return true;
}

/**
 * Return the selected columns in the order chosen by the user.
 *
 * @param {'code'|'desc'|'hierarchy'} type
 * @returns {string[]}
 */
export function getOrderedSelection(type) {
    const selection = type === 'code' ? importData.codeSelection
        : type === 'desc' ? importData.descSelection
            : importData.hierarchySelection;
    return Object.entries(selection)
        .filter(([, order]) => order > 0)
        .sort((a, b) => a[1] - b[1])
        .map(([col]) => col);
}

/**
 * Convert the raw rows into import-ready records.
 *
 * For each row:
 *   - code: join selected code columns with codeSeparator
 *   - description: join desc columns with descSeparator, then run
 *     cleaning rules
 *   - hierarchy: join hierarchy columns with " → ", running cleaning
 *     rules on each level separately (so a pattern like
 *     ^Раздел matches each level)
 *
 * @returns {Array<{code: string, description: string, hierarchy: string|null, meta: Object}>}
 */
export function buildRecordsFromMapping() {
    const codeCols = getOrderedSelection('code');
    const descCols = getOrderedSelection('desc');
    const hierarchyCols = getOrderedSelection('hierarchy');
    const codeSeparator = importData.codeSeparator || '.';
    const descSeparator = importData.descSeparator || ' ';

    return importData.raw.map((row) => {
        const cleanValue = (val) => {
            if (!val) return '';
            return stripSymmetricQuotes(String(val).trim());
        };

        const code = codeCols.map((c) => cleanValue(row[c])).filter(Boolean).join(codeSeparator);

        let description = descCols.map((c) => cleanValue(row[c])).filter(Boolean).join(descSeparator);
        description = applyCleaningRules(description, 'description');

        let hierarchy = null;
        if (hierarchyCols.length > 0) {
            const parts = hierarchyCols.map((c) => {
                let val = cleanValue(row[c]);
                val = applyCleaningRules(val, 'hierarchy_level');
                return val;
            }).filter(Boolean);
            hierarchy = parts.join(' → ');
        }

        return { code, description, hierarchy, meta: row };
    }).filter((r) => r.code && r.description);
}
