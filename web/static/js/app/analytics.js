/**
 * Analytics events: copy / dislike.
 *
 * Sends a POST to /feedback/copy or /feedback/dislike with the
 * relevant payload. The server may or may not store it; this is a
 * best-effort fire-and-forget.
 */

import { appState } from './state.js';
import { addSessionHeader } from '../shared/session.js';

/**
 * @param {'copy'|'dislike'} type
 * @param {{code: string, rank: number, description: string, reranker_score: number, cosine_similarity: number}} payload
 */
export function sendAnalytics(type, payload) {
    if (type === 'copy') {
        const copyData = {
            query: appState.currentQuery,
            selected_code: payload.code,
            position: payload.rank,
            description: payload.description,
            database: appState.currentDatabase,
            reranker_score: payload.reranker_score,
            cosine_similarity: payload.cosine_similarity,
        };
        fetch('/feedback/copy', {
            method: 'POST',
            headers: addSessionHeader({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(copyData),
        })
            .then((res) => res.json())
            .then((data) => console.log('✅ Copy event записан:', data))
            .catch((e) => console.error('❌ Ошибка записи copy event:', e));
    } else if (type === 'dislike') {
        const dislikeData = {
            timestamp: new Date().toISOString(),
            query: appState.currentQuery,
            selected_code: payload.code,
            position: payload.rank,
            description: payload.description,
            database: appState.currentDatabase,
            reranker_score: payload.reranker_score,
            cosine_similarity: payload.cosine_similarity,
            action: 'dislike',
        };
        fetch('/feedback/dislike', {
            method: 'POST',
            headers: addSessionHeader({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(dislikeData),
        })
            .then((res) => res.json())
            .then((data) => console.log('✅ Dislike event записан:', data))
            .catch((e) => console.error('❌ Ошибка записи dislike event:', e));
    }
}
