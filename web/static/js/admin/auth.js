/**
 * Admin authentication: login form, JWT validation, logout.
 *
 * Tokens are stored in localStorage under the key `adminToken`. On 401
 * the shared authFetch() triggers a reload — this module just exposes
 * the login UX.
 */

import { state } from './state.js';
import { els } from './els.js';
import { switchView } from './navigation.js';
import { startJobPoller } from './import/jobs-list.js';

/**
 * Wire up the login screen, password field and logout button.
 */
export function initAuth() {
    // If a token is already in storage, show the dashboard immediately and
    // validate the token in the background. A stale token will be cleared by
    // authFetch() when the first request 401s and the page reloads.
    if (state.token) {
        showApp();
        validateToken().then((valid) => {
            if (!valid) logout();
        });
    } else {
        els.loginScreen?.classList.remove('hidden');
    }

    els.authBtn?.addEventListener('click', attemptLogin);
    els.authPassword?.addEventListener('keyup', (e) => {
        if (e.key === 'Enter') attemptLogin();
    });

    els.logoutBtn?.addEventListener('click', logout);
}

/**
 * Verify the cached token by hitting a guarded endpoint. Returns true when
 * the server accepts the token, false otherwise (network errors included).
 *
 * @returns {Promise<boolean>}
 */
export async function validateToken() {
    if (!state.token) return false;
    try {
        const res = await fetch('/admin/collections', {
            headers: { Authorization: `Bearer ${state.token}` },
        });
        return res.ok;
    } catch {
        return false;
    }
}

/**
 * Reveal the dashboard and start background activity.
 */
export function showApp() {
    els.loginScreen?.classList.add('hidden');
    els.adminApp?.classList.remove('hidden');
    switchView('collections');
    startJobPoller();
}

/**
 * POST /admin/auth with the entered password. On success, store the JWT
 * and reveal the dashboard.
 */
export async function attemptLogin() {
    const pwd = els.authPassword.value;

    els.authBtn.disabled = true;
    els.authBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Вход...';
    els.authError?.classList.add('hidden');

    try {
        const res = await fetch('/admin/auth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: pwd }),
        });

        if (res.ok) {
            const data = await res.json();
            state.token = data.token;
            try {
                localStorage.setItem('adminToken', data.token);
            } catch {
                /* storage unavailable */
            }
            const expiresHours = Math.round((data.expires_in || 0) / 3600);
            console.log(`✅ Вход выполнен. Токен действителен ${expiresHours} часов.`);
            showApp();
        } else {
            const error = await res.json().catch(() => ({}));
            if (els.authError) {
                if (res.status === 429) {
                    els.authError.textContent = error.detail || 'Слишком много попыток. Подождите.';
                } else {
                    els.authError.textContent = error.detail || 'Неверный пароль';
                }
                els.authError.classList.remove('hidden');
            }
        }
    } catch (e) {
        console.error('Login error:', e);
        if (els.authError) {
            els.authError.textContent = 'Ошибка подключения к серверу';
            els.authError.classList.remove('hidden');
        }
    } finally {
        els.authBtn.disabled = false;
        els.authBtn.innerHTML = 'Войти';
    }
}

/**
 * Clear the token and reload. Used both by the explicit logout button and
 * by validateToken() when a cached token is rejected.
 */
export function logout() {
    state.token = null;
    try {
        localStorage.removeItem('adminToken');
    } catch {
        /* storage unavailable */
    }
    location.reload();
}
