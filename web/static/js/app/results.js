/**
 * Result table rendering and the "clear results" helper.
 */

import { els, setStatusInfoColor } from './els.js';
import { appState } from './state.js';
import { escapeHtml } from '../shared/dom.js';
import { createScoreBar } from './search.js';

/**
 * Render the search-result table.
 *
 * @param {Object} data - /match response
 * @param {string} data.query
 * @param {Array}  data.candidates
 * @param {number} data.processing_time
 */
export function displayResults(data) {
    appState.currentQuery = data.query;
    appState.currentResults = data.candidates;
    if (els.processingTimeElement) {
        els.processingTimeElement.textContent = data.processing_time.toFixed(2) + 's';
    }
    if (els.statusInfo) {
        els.statusInfo.textContent = `Найдено: ${data.candidates.length}`;
        setStatusInfoColor('success');
    }

    const db = appState.databases.find((d) => d.name === appState.currentDatabase);
    const dbName = db ? db.description.split('(')[0] : appState.currentDatabase;

    let infoText = `Поиск завершен по базе "${dbName}"`;
    // Note: the current app doesn't expose currentFilterPath here
    // (we use the multi-select state instead), but we keep the
    // "in category" suffix when there's a single-path legacy filter.
    if (els.processingInfo) {
        els.processingInfo.textContent = infoText;
    }

    if (!els.resultsBody) return;

    if (data.candidates.length === 0) {
        els.resultsBody.innerHTML = `
            <tr><td colspan="6" style="text-align: center; padding: 40px 20px; color: var(--text-secondary);">
                <i class="fas fa-search" aria-hidden="true" style="font-size: 2rem; margin-bottom: 15px; display: block; opacity: 0.5"></i>
                Ничего не найдено по вашему запросу.<br>Попробуйте переформулировать или изменить параметры поиска.
            </td></tr>`;
        if (els.statusInfo) {
            els.statusInfo.textContent = 'Ничего не найдено';
            setStatusInfoColor('warning');
        }
        return;
    }

    let html = '';
    data.candidates.forEach((c) => {
        const isTop = c.rank === 1;
        const materialName = c.material_name || c.description;
        const categoryPath = c.category_path || '';
        const categoryPathDisplay = categoryPath ? categoryPath.replace(/ → /g, ' / ') : '';
        const categoryHtml = categoryPath
            ? `<div class="result-category-path" data-category-path="${escapeHtml(categoryPath)}" title="Перейти в каталог: ${escapeHtml(categoryPath)}">
                   <i class="fas fa-folder" aria-hidden="true"></i>
                   <span>${escapeHtml(categoryPathDisplay)}</span>
               </div>`
            : '';

        html += `
            <tr data-rank="${c.rank}">
                <td style="font-weight:bold; color:${isTop ? 'var(--success)' : 'var(--text-secondary)'}">${c.rank}</td>
                <td>
                    <span class="code-text">${escapeHtml(c.code)}</span>
                </td>
                <td class="copy-cell">
                    <button class="copy-btn" title="Копировать">
                        <i class="fas fa-copy" aria-hidden="true"></i>
                    </button>
                </td>
                <td class="description-cell">
                    <div class="result-material-name">${escapeHtml(materialName)}</div>
                    ${categoryHtml}
                </td>
                <td class="copy-cell">
                    <button class="dislike-btn" data-rank="${c.rank}">
                        <i class="far fa-thumbs-down" aria-hidden="true"></i>
                    </button>
                </td>
                <td>
                    <div class="score-wrapper">
                        <span class="score-label">Rerank: ${c.reranker_score.toFixed(4)}</span>
                        ${createScoreBar(c.reranker_score)}
                    </div>
                    <div class="score-wrapper">
                        <span class="score-label">Cosine: ${c.cosine_similarity.toFixed(4)}</span>
                        ${createScoreBar(c.cosine_similarity)}
                    </div>
                </td>
            </tr>
        `;
    });
    els.resultsBody.innerHTML = html;
}

/**
 * Replace the results table with a single "results cleared" row and
 * reset the status / error UI.
 */
export function clearResults() {
    if (!els.resultsBody) return;
    els.resultsBody.innerHTML = `
        <tr><td colspan="6" style="text-align: center; padding: 60px 20px; color: var(--text-secondary);">
        Результаты очищены</td></tr>`;
    els.errorContainer?.classList.add('hidden');
    if (els.statusInfo) {
        els.statusInfo.textContent = 'Готов к работе';
        setStatusInfoColor('success');
    }
}
