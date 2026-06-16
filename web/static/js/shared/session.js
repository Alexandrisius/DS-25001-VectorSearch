/**
 * Session ID management.
 *
 * Generates a stable per-browser UUID on first visit and stores it in
 * localStorage. Every authenticated request can then send it as
 * `X-Session-ID`, allowing the server to group the actions of one
 * person even when they share an IP (e.g. office NAT).
 *
 * Usage:
 *   import { getSessionId, addSessionHeader } from '../shared/session.js';
 *   fetch('/match', { headers: addSessionHeader({ ... }) });
 */

const STORAGE_KEY = 'ksrSessionId';

function uuid4() {
    if (crypto?.randomUUID) return crypto.randomUUID();
    // Fallback для очень старых браузеров
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
    });
}

/**
 * Returns the current session id, creating one if needed. Always
 * non-null in normal browsers; null only if localStorage is broken.
 *
 * @returns {string|null}
 */
export function getSessionId() {
    try {
        let id = localStorage.getItem(STORAGE_KEY);
        if (!id) {
            id = uuid4();
            localStorage.setItem(STORAGE_KEY, id);
        }
        return id;
    } catch {
        return null;
    }
}

/**
 * Adds the X-Session-ID header to an existing headers object (or
 * creates a new one). Returns the same object for chaining.
 *
 * @param {HeadersInit} [headers]
 * @returns {HeadersInit}
 */
export function addSessionHeader(headers = {}) {
    const id = getSessionId();
    if (!id) return headers;
    return { ...headers, 'X-Session-ID': id };
}
