/**
 * Shared DOM utilities.
 * Used by both admin/ and app/ modules.
 */

/**
 * Escape HTML special characters for safe insertion into innerHTML.
 * Uses the DOM API (safer than regex replacement because it correctly
 * handles edge cases like lone `&` characters).
 *
 * @param {unknown} text
 * @returns {string}
 */
export function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

/**
 * Truncate text to maxLength, appending "..." if cut.
 *
 * @param {string} text
 * @param {number} maxLength
 * @returns {string}
 */
export function truncate(text, maxLength) {
    if (!text) return '';
    const str = String(text);
    if (str.length <= maxLength) return str;
    return str.substring(0, maxLength) + '...';
}

/**
 * Format an ISO 8601 timestamp as DD.MM.YYYY HH:MM (local time).
 *
 * @param {string|null|undefined} isoString
 * @returns {string} formatted date or "—" for empty/invalid input
 */
export function formatDateTime(isoString) {
    if (!isoString) return '—';
    try {
        const date = new Date(isoString);
        if (Number.isNaN(date.getTime())) return '—';
        const day = String(date.getDate()).padStart(2, '0');
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const year = date.getFullYear();
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        return `${day}.${month}.${year} ${hours}:${minutes}`;
    } catch {
        return '—';
    }
}

/**
 * Format an integer with thousands separators using the supplied locale.
 *
 * @param {number|null|undefined} value
 * @param {string} [locale="ru-RU"]
 * @returns {string}
 */
export function formatNumber(value, locale = 'ru-RU') {
    if (value === null || value === undefined) return '0';
    try {
        return new Intl.NumberFormat(locale).format(Number(value) || 0);
    } catch {
        return String(value);
    }
}
