/**
 * App entry point.
 *
 * Wires every module together. Import order matters — modules with
 * no internal dependencies come first.
 */

import { els } from './els.js';
import { appState, filterState } from './state.js';

import { initTheme } from './theme.js';
import { loadAvailableDatabases } from './database.js';
import { initCustomSelect } from './custom-select.js';
import { initCatalogSidebar } from './catalog/sidebar.js';
import { initCatalogSearch } from './catalog/search.js';

import { performSearch, setLoading } from './search.js';
import { clearResults } from './results.js';
import { sendAnalytics } from './analytics.js';
import { clearFilter } from './filter.js';
import { navigateToCategoryInCatalog } from './catalog/navigation.js';

document.addEventListener('DOMContentLoaded', () => {
    // Focus the search input on load.
    els.queryInput?.focus();

    // Bootstrap data.
    loadAvailableDatabases();
    initTheme();
    initCustomSelect();
    initCatalogSidebar();
    initCatalogSearch();

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

    // Delegated handlers for the results table.
    document.addEventListener('click', (e) => {
        // Copy code
        const copyBtn = e.target.closest('.copy-btn');
        if (copyBtn) {
            const btn = copyBtn;
            const row = btn.closest('tr');
            if (!row) return;
            const code = row.querySelector('.code-text')?.textContent || '';
            const rank = parseInt(row.dataset.rank, 10);
            navigator.clipboard.writeText(code).then(() => {
                const originalHtml = btn.innerHTML;
                btn.innerHTML = '<i class="fas fa-check" style="color:var(--success)"></i>';
                setTimeout(() => { btn.innerHTML = originalHtml; }, 1500);
                if (appState.currentQuery && appState.currentResults.length > 0) {
                    const result = appState.currentResults.find((r) => r.rank === rank);
                    if (result) {
                        sendAnalytics('copy', {
                            code: result.code,
                            rank: result.rank,
                            description: result.description,
                            reranker_score: result.reranker_score,
                            cosine_similarity: result.cosine_similarity,
                        });
                    }
                }
            });
            return;
        }

        // Dislike
        const dislikeBtn = e.target.closest('.dislike-btn');
        if (dislikeBtn) {
            const btn = dislikeBtn;
            const row = btn.closest('tr');
            if (!row) return;
            const rank = parseInt(row.dataset.rank, 10);
            btn.innerHTML = '<i class="fas fa-thumbs-down" style="color:var(--danger)"></i>';
            if (appState.currentQuery && appState.currentResults.length > 0) {
                const result = appState.currentResults.find((r) => r.rank === rank);
                if (result) {
                    sendAnalytics('dislike', {
                        code: result.code,
                        rank: result.rank,
                        description: result.description,
                        reranker_score: result.reranker_score,
                        cosine_similarity: result.cosine_similarity,
                    });
                }
            }
            return;
        }

        // Database card click → select database
        const dbCard = e.target.closest('.db-card');
        if (dbCard) {
            const dbName = dbCard.dataset.name;
            const option = els.customOptionsContainer
                ? Array.from(els.customOptionsContainer.children).find((div) => div.dataset.value === dbName)
                : null;
            if (option) option.click();
            return;
        }

        // Result category path → navigate in catalog
        const catPath = e.target.closest('.result-category-path');
        if (catPath) {
            const categoryPath = catPath.dataset.categoryPath;
            if (categoryPath) {
                navigateToCategoryInCatalog(categoryPath);
            }
        }
    });
});

/* silence unused */
void setLoading;
void filterState;
