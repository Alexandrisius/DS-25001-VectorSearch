/**
 * Click + long-press handlers for the results table.
 *
 * The `#resultsBody` rows are re-rendered on every search, so
 * instead of wiring per-row listeners we install a single
 * document-level click delegation that finds the closest
 * .copy-btn or .dislike-btn and dispatches accordingly.
 *
 * Split out of app/main.js (115 LoC) for module size management
 * and to keep main.js as a pure bootstrap file.
 */

import { appState } from './state.js';
import { sendAnalytics } from './analytics.js';
import { setStatusInfoColor } from './els.js';

/**
 * Install the delegated handler. Idempotent — safe to call more
 * than once.
 */
let installed = false;
export function initResultsHandlers() {
    if (installed) return;
    installed = true;

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
                btn.innerHTML = '<i class="fas fa-check" aria-hidden="true" style="color:var(--success)"></i>';
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
            btn.innerHTML = '<i class="fas fa-thumbs-down" aria-hidden="true" style="color:var(--danger)"></i>';
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
    });
}
