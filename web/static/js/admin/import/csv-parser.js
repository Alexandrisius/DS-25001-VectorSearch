/**
 * RFC-4180-style CSV/TSV parser, plus symmetric-quote stripping and
 * text normalization helpers used by the diff analyzer.
 */

/**
 * Strip symmetric pairs of quotes from the beginning and end of a
 * string, repeatedly, until no more can be removed.
 *
 * @param {string|null|undefined} text
 * @returns {string}
 */
export function stripSymmetricQuotes(text) {
    if (!text || text.length < 2) return text || '';

    const quotePairs = [
        ['"', '"'],
        ["'", "'"],
        ['«', '»'],
        ['„', '"'],
        ['"', '"'],
        ['`', '`'],
    ];

    let result = text.trim();
    let changed = true;

    while (changed && result.length >= 2) {
        changed = false;
        for (const [open, close] of quotePairs) {
            if (result.startsWith(open) && result.endsWith(close)) {
                result = result.slice(open.length, -close.length).trim();
                changed = true;
                break;
            }
        }
    }

    return result;
}

/**
 * Normalize text for diff comparison.
 *
 * - Strip symmetric quotes
 * - Lowercase
 * - Normalise line endings (\r\n / \r → \n)
 * - Collapse spaces and tabs
 * - Trim each line
 * - Drop empty lines
 * - Trim overall
 *
 * @param {string|null|undefined} text
 * @returns {string}
 */
export function normalizeText(text) {
    if (!text) return '';
    const normalized = stripSymmetricQuotes(text);
    return normalized.toLowerCase()
        .replace(/\r\n/g, '\n')
        .replace(/\r/g, '\n')
        .replace(/[ \t]+/g, ' ')
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line)
        .join('\n')
        .trim();
}

/**
 * Parse CSV/TSV per RFC 4180.
 *
 * - Handles fields in quotes: "value"
 * - Handles escaped quotes inside fields: "text ""quoted"" text"
 * - Handles delimiters inside quoted fields: "a;b;c" → one field
 * - Handles multiline quoted fields
 *
 * @param {string} text
 * @param {string} delimiter
 * @returns {Array<Array<string>>}
 */
export function parseCSV(text, delimiter) {
    const rows = [];
    let currentRow = [];
    let currentField = '';
    let inQuotes = false;
    let i = 0;

    text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

    while (i < text.length) {
        const char = text[i];
        const nextChar = text[i + 1];

        if (inQuotes) {
            if (char === '"') {
                if (nextChar === '"') {
                    currentField += '"';
                    i += 2;
                } else {
                    inQuotes = false;
                    i++;
                }
            } else {
                currentField += char;
                i++;
            }
        } else {
            if (char === '"') {
                inQuotes = true;
                i++;
            } else if (char === delimiter) {
                currentRow.push(currentField);
                currentField = '';
                i++;
            } else if (char === '\n') {
                currentRow.push(currentField);
                if (currentRow.some((cell) => cell.trim())) {
                    rows.push(currentRow);
                }
                currentRow = [];
                currentField = '';
                i++;
            } else {
                currentField += char;
                i++;
            }
        }
    }

    if (currentField || currentRow.length > 0) {
        currentRow.push(currentField);
        if (currentRow.some((cell) => cell.trim())) {
            rows.push(currentRow);
        }
    }

    return rows;
}
