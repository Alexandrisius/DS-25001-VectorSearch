/**
 * Shared HTTP / auth helpers.
 * Used by both admin/ and app/ modules where authentication is required.
 *
 * Admin endpoints (under /admin/* and /auth) require a JWT bearer token
 * stored in localStorage under the key `adminToken`. The authFetch wrapper
 * attaches the header automatically and triggers a hard reload on 401.
 */

import { STORAGE_KEYS } from './constants.js';

/**
 * Read the JWT token from localStorage. Returns empty string when missing.
 *
 * @returns {string}
 */
export function getAdminToken() {
    try {
        return localStorage.getItem(STORAGE_KEYS.adminToken) || '';
    } catch {
        return '';
    }
}

/**
 * Build the standard request headers for admin endpoints.
 *
 * @param {Object} [extra]
 * @returns {Object}
 */
export function getAuthHeaders(extra = {}) {
    return {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getAdminToken()}`,
        ...extra,
    };
}

/**
 * Issue a fetch against an admin endpoint, automatically attaching the JWT
 * token and forcing a page reload on 401 (which clears the stale token and
 * returns the user to the login screen).
 *
 * @param {string} url
 * @param {RequestInit} [options]
 * @returns {Promise<Response>}
 * @throws {Error} with message "Unauthorized" on 401, or "Нет связи" on network failure
 */
export async function authFetch(url, options = {}) {
    const headers = {
        ...getAuthHeaders(),
        ...(options.headers || {}),
    };

    let res;
    try {
        res = await fetch(url, { ...options, headers });
    } catch (e) {
        throw new Error('Нет связи с сервером: ' + e.message);
    }

    if (res.status === 401) {
        // Token expired or invalid — clear and reload so the user lands on login.
        console.warn('🔒 JWT токен истёк или невалиден');
        try {
            localStorage.removeItem(STORAGE_KEYS.adminToken);
        } catch {
            /* localStorage may be unavailable in some sandboxes */
        }
        location.reload();
        throw new Error('Unauthorized');
    }

    return res;
}

/**
 * Convenience wrapper: authFetch + JSON parsing in one call.
 *
 * @param {string} url
 * @param {RequestInit} [options]
 * @returns {Promise<any>}
 */
export async function fetchJson(url, options = {}) {
    const res = await authFetch(url, options);
    return res.json();
}
