/**
 * App entry point.
 *
 * Pure bootstrap: each `init*` function installs its own listeners.
 * Import order matters — modules with no internal dependencies are
 * imported first, then modules that depend on them. No cycles.
 */

import { els } from './els.js';
import { appState } from './state.js';

import { initTheme } from './theme.js';
import { loadAvailableDatabases } from './database.js';
import { initCatalogSidebar } from './catalog/sidebar.js';
import { initCatalogControls } from './catalog/sidebar-controls.js';
import { initCatalogSearch } from './catalog/search.js';

import { performSearch } from './search.js';
import { clearResults } from './results.js';
import { sendAnalytics } from './analytics.js';
import { clearFilter } from './filter.js';
import { initResultsHandlers } from './results-handlers.js';
import { initCatalogHandlers } from './catalog-handlers.js';

document.addEventListener('DOMContentLoaded', () => {
    // Don't autofocus the search input — that would steal the first Tab
    // from the skip-link, breaking keyboard a11y (WCAG 2.4.1).
    // The search input still receives focus on click and on Enter.

    // Bootstrap data.
    loadAvailableDatabases();
    initTheme();
    initCatalogSidebar();
    initCatalogControls();
    initCatalogSearch();
    initResultsHandlers();
    initCatalogHandlers();

    // Search wiring.
    els.clearBtn?.addEventListener('click', () => {
        if (els.queryInput) {
            els.queryInput.value = '';
            els.queryInput.focus();
        }
        clearResults();
        if (els.processingInfo) els.processingInfo.textContent = 'Ожидание запроса...';
        if (els.processingTimeElement) els.processingTimeElement.textContent = '0.00s';
        appState.currentResults = [];
        clearFilter();
    });
    els.searchBtn?.addEventListener('click', performSearch);
    els.queryInput?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            performSearch();
        }
    });
});

// Re-export sendAnalytics so legacy callers (tests, dev tools) keep working.
export { sendAnalytics };
