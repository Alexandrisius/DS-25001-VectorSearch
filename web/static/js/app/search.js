/**
 * Search box logic: kick off /match on click or Enter, manage the
 * loading state and inline error.
 */

import { els, setStatusInfoColor } from './els.js';
import { appState, filterState } from './state.js';
import { displayResults } from './results.js';

/**
 * Lock the search button and show the "Searching…" spinner.
 *
 * @param {boolean} loading
 */
export function setLoading(loading) {
    if (!els.searchBtn) return;
    els.searchBtn.disabled = loading;
    if (loading) {
        els.searchBtn.innerHTML = '<div class="loading-spinner"></div> Ищем...';
        if (els.statusInfo) {
            els.statusInfo.textContent = 'Поиск...';
            setStatusInfoColor('primary');
        }
        if (els.processingInfo) {
            els.processingInfo.textContent = 'Нейросеть обрабатывает запрос...';
        }
    } else {
        els.searchBtn.innerHTML = '<i class="fas fa-bolt" aria-hidden="true"></i> Найти';
    }
}

/**
 * Run a search.
 *
 * Filter precedence:
 *   1. Multi-select paths (Ctrl+click) → OR across them
 *   2. Single-select path (legacy filter_path) → single
 *   3. No filter → search everywhere
 */
export async function performSearch() {
    const q = els.queryInput?.value.trim();
    if (!q) return;

    setLoading(true);
    els.errorContainer?.classList.add('hidden');

    try {
        const requestBody = {
            text: q,
            database: appState.currentDatabase,
            max_results: 50,
        };

        const selected = filterState.selectedPaths;
        if (selected && selected.length > 0) {
            requestBody.filter_paths = selected.map((p) => ({ path: p.path, level: p.level }));
            console.log(`🔍 Поиск с множественным фильтром (${selected.length} категорий):`, requestBody.filter_paths);
        } else if (filterState.currentFilterPath && filterState.currentFilterLevel) {
            requestBody.filter_path = filterState.currentFilterPath;
            requestBody.filter_level = filterState.currentFilterLevel;
            console.log(`🔍 Поиск с фильтром: level=${filterState.currentFilterLevel}, path="${filterState.currentFilterPath}"`);
        }

        const res = await fetch('/match', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody),
        });
        if (!res.ok) throw new Error('Ошибка соединения с сервером');

        const data = await res.json();
        displayResults(data);
    } catch (e) {
        if (els.errorContainer) {
            els.errorContainer.textContent = e.message;
            els.errorContainer.classList.remove('hidden');
        }
        if (els.statusInfo) {
            els.statusInfo.textContent = 'Ошибка';
            setStatusInfoColor('danger');
        }
        if (els.processingInfo) {
            els.processingInfo.textContent = 'Произошла ошибка при поиске';
        }
    } finally {
        setLoading(false);
    }
}

/**
 * Build the HTML for a score-bar (0..1 → 0..100%).
 *
 * @param {number} val
 * @returns {string}
 */
export function createScoreBar(val) {
    const pct = Math.min(100, val * 100);
    return `<div class="progress-bg"><div class="progress-fill" style="width:${pct}%"></div></div>`;
}
