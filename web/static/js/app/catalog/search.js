/**
 * Catalog semantic search: input + dropdown of matching categories.
 *
 * Triggered by typing in the sidebar's search box. The actual match
 * is done server-side via /hierarchy/<db>/search; the response is
 * a list of categories ranked by reranker / hit count.
 */

import { els } from '../els.js';
import { appState, filterState } from '../state.js';
import { escapeHtml } from '../../shared/dom.js';
import { SEARCH_DEBOUNCE_MS } from '../../shared/constants.js';
import { selectCategoryFromSearch } from './navigation.js';

/** Module-level timer id for the debounce; set/cleared on each input. */
let catalogSearchDebounce = null;

/**
 * Wire up the catalog-search input. Called once at bootstrap.
 */
export function initCatalogSearch() {
    if (!els.catalogSearchInput) return;

    const trigger = () => {
        const query = els.catalogSearchInput.value.trim();
        if (els.catalogSearchClear) {
            els.catalogSearchClear.classList.toggle('hidden', query.length === 0);
        }
        if (catalogSearchDebounce) clearTimeout(catalogSearchDebounce);
        if (query.length >= 2) {
            catalogSearchDebounce = setTimeout(() => performCatalogSearch(query), SEARCH_DEBOUNCE_MS);
        } else {
            hideCatalogSearchResults();
        }
    };

    els.catalogSearchInput.addEventListener('input', trigger);

    els.catalogSearchClear?.addEventListener('click', () => {
        els.catalogSearchInput.value = '';
        els.catalogSearchClear.classList.add('hidden');
        hideCatalogSearchResults();
        els.catalogSearchInput.focus();
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.catalog-search')) {
            hideCatalogSearchResults();
        }
    });

    els.catalogSearchInput.addEventListener('focus', () => {
        const query = els.catalogSearchInput.value.trim();
        if (query.length >= 2 && els.catalogSearchResults.innerHTML) {
            els.catalogSearchResults.classList.remove('hidden');
        }
    });
}

/**
 * Run a catalog semantic search and display the matches.
 *
 * @param {string} query
 */
export async function performCatalogSearch(query) {
    if (!els.catalogSearchResults) return;
    els.catalogSearchResults.classList.remove('hidden');
    els.catalogSearchResults.classList.add('loading');
    els.catalogSearchResults.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Поиск категорий...';

    try {
        const res = await fetch(`/hierarchy/${appState.currentDatabase}/search`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: query, top_k: 10 }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        displayCatalogSearchResults(data.categories);
    } catch (e) {
        console.error('❌ Ошибка поиска категорий:', e);
        els.catalogSearchResults.innerHTML = [
            '<div class="catalog-search-empty">',
            '<i class="fas fa-exclamation-triangle" aria-hidden="true" style="color: var(--danger);"></i>',
            '<div>Ошибка поиска</div>',
            '</div>',
        ].join('');
    } finally {
        els.catalogSearchResults.classList.remove('loading');
    }
}

/**
 * Render the result list. Each result is clickable; Ctrl+click
 * multi-selects instead of navigating.
 *
 * @param {Array} categories
 */
export function displayCatalogSearchResults(categories) {
    if (!els.catalogSearchResults) return;

    if (!categories || categories.length === 0) {
        els.catalogSearchResults.innerHTML = [
            '<div class="catalog-search-empty">',
            '<i class="fas fa-folder-open" aria-hidden="true" style="opacity: 0.5;"></i>',
            '<div>Категории не найдены</div>',
            '</div>',
        ].join('');
        return;
    }

    let html = [
        '<div class="catalog-search-hint">',
        '<i class="fas fa-keyboard" aria-hidden="true"></i> Ctrl+клик для добавления в фильтр',
        '</div>',
    ].join('');

    categories.forEach((cat) => {
        const scoreText = cat.rerank_score
            ? `${(cat.rerank_score * 100).toFixed(0)}%`
            : `${cat.hits} совп.`;

        const isSelected = filterState.selectedPaths.some((p) => p.path === cat.path);
        const selectedClass = isSelected ? ' selected' : '';

        const folderName = cat.name || cat.path.split(' → ').pop();

        html += [
            `<div class="catalog-search-result${selectedClass}"`,
            `     data-path="${escapeHtml(cat.path)}"`,
            `     data-level="${cat.level}">`,
            '    <div class="catalog-search-result-name">',
            isSelected ? '<i class="fas fa-check-circle" aria-hidden="true" style="color: var(--success); margin-right: 5px;"></i>' : '',
            '<i class="fas fa-folder" aria-hidden="true" style="color: #f59e0b; margin-right: 5px;"></i>',
            `        ${escapeHtml(folderName)}`,
            `        <span class="catalog-search-result-score">${scoreText}</span>`,
            '    </div>',
            `    <div class="catalog-search-result-path">${escapeHtml(cat.path)}</div>`,
            '</div>',
        ].join('');
    });

    els.catalogSearchResults.innerHTML = html;

    // Delegate click on each result.
    els.catalogSearchResults.querySelectorAll('.catalog-search-result').forEach((result) => {
        result.addEventListener('click', async (event) => {
            const path = result.dataset.path;
            const level = parseInt(result.dataset.level, 10);
            await selectCategoryFromSearch(path, level, event);
            if (event.ctrlKey || event.metaKey) {
                const isNowSelected = filterState.selectedPaths.some((p) => p.path === path);
                result.classList.toggle('selected', isNowSelected);
                const nameEl = result.querySelector('.catalog-search-result-name');
                const checkIcon = nameEl.querySelector('.fa-check-circle');
                if (isNowSelected && !checkIcon) {
                    nameEl.insertAdjacentHTML(
                        'afterbegin',
                        '<i class="fas fa-check-circle" aria-hidden="true" style="color: var(--success); margin-right: 5px;"></i>',
                    );
                } else if (!isNowSelected && checkIcon) {
                    checkIcon.remove();
                }
            } else {
                hideCatalogSearchResults();
                els.catalogSearchInput.value = '';
                els.catalogSearchClear?.classList.add('hidden');
            }
        });
    });
}

/**
 * Hide the result dropdown.
 */
export function hideCatalogSearchResults() {
    els.catalogSearchResults?.classList.add('hidden');
}
