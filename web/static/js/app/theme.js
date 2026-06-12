/**
 * Light/dark theme toggle.
 *
 * The current theme is stored in localStorage under the `theme` key
 * (see shared/constants.js). The default is `dark`.
 */

import { els } from './els.js';
import { STORAGE_KEYS } from '../shared/constants.js';

const THEME_KEY = STORAGE_KEYS.theme;
const DEFAULT_THEME = 'dark';

/**
 * Initialise the theme: read from storage, fall back to dark.
 * Called once at bootstrap.
 */
export function initTheme() {
    let saved = DEFAULT_THEME;
    try {
        saved = localStorage.getItem(THEME_KEY) || DEFAULT_THEME;
    } catch {
        saved = DEFAULT_THEME;
    }
    setTheme(saved);

    els.themeToggle?.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        setTheme(next);
    });
}

/**
 * Apply a theme to the document and update the toggle button label.
 *
 * @param {'dark'|'light'} theme
 */
export function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try {
        localStorage.setItem(THEME_KEY, theme);
    } catch {
        /* storage unavailable */
    }

    if (theme === 'dark') {
        els.themeIcon?.classList.remove('fa-moon');
        els.themeIcon?.classList.add('fa-sun');
        if (els.themeText) els.themeText.textContent = 'Светлая тема';
    } else {
        els.themeIcon?.classList.remove('fa-sun');
        els.themeIcon?.classList.add('fa-moon');
        if (els.themeText) els.themeText.textContent = 'Тёмная тема';
    }
}
