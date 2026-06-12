/**
 * Background-job tracking: WebSocket subscription with auto-reconnect
 * via polling.
 *
 * watchJob is the entry-point used by the import wizard. It opens a
 * WebSocket to /admin/jobs/{id}/ws and listens for status updates.
 * Falls back to pollJob() on any error or after a 60s watchdog with
 * no updates.
 *
 * The invalidateHierarchy() helper is exposed for re-use by the
 * apply-diff flow (run-apply.js).
 *
 * Split out of the original jobs.js for module size management.
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { authFetch } from '../../shared/api.js';
import { JOB_STATUS_LABELS, JOB_WATCHDOG_TIMEOUT } from '../../shared/constants.js';
import { closeModal } from '../modals.js';
import { loadCollections } from '../collections/list.js';
import { loadJobs } from './jobs-list.js';
import { pollJob } from './jobs-poll.js';

/**
 * Subscribe to a job's progress via WebSocket. Falls back to
 * pollJob() on any error or after a 60s watchdog with no updates.
 *
 * @param {string} jobId
 */
export function watchJob(jobId) {
    if (state.jobWs) {
        try { state.jobWs.close(); } catch { /* already closed */ }
        state.jobWs = null;
    }
    if (state.jobInterval) {
        clearInterval(state.jobInterval);
        state.jobInterval = null;
    }

    els.importStatusText.innerText = 'В очереди...';
    els.importProgress.style.width = '0%';

    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const token = localStorage.getItem('adminToken') || sessionStorage.getItem('adminToken') || '';
    const url = `${proto}://${location.host}/admin/jobs/${jobId}/ws?token=${encodeURIComponent(token)}`;
    console.log('[watchJob] connecting to', url);

    /** @type {WebSocket|null} */
    let ws = null;
    try {
        ws = new WebSocket(url);
    } catch (e) {
        console.error('[watchJob] WebSocket construction failed:', e);
        pollJob(jobId);
        return;
    }
    state.jobWs = ws;

    let lastUpdate = Date.now();
    const watchDog = setInterval(() => {
        if (Date.now() - lastUpdate > JOB_WATCHDOG_TIMEOUT) {
            console.warn('[watchJob] no updates for 60s, fallback to polling');
            try { ws.close(); } catch { /* ignore */ }
            state.jobWs = null;
            pollJob(jobId);
            clearInterval(watchDog);
        }
    }, 10000);

    ws.onopen = () => {
        console.log('[watchJob] WebSocket open');
        lastUpdate = Date.now();
    };

    ws.onmessage = (ev) => {
        lastUpdate = Date.now();
        let msg;
        try { msg = JSON.parse(ev.data); } catch { return; }
        console.log('[watchJob] update:', msg);
        if (msg.type === 'progress' || msg.type === 'status') {
            const j = msg.data || msg;
            els.importProgress.style.width = `${j.progress || 0}%`;
            const st = j.status || 'pending';
            const detail = j.details ? ` — ${j.details}` : '';
            els.importStatusText.innerText = `${JOB_STATUS_LABELS[st] || st} (${j.progress || 0}%)${detail}`;
        } else if (msg.type === 'done') {
            const j = msg.data || msg;
            els.importProgress.style.width = '100%';
            els.importStatusText.innerText = 'Завершено';
            try { ws.close(); } catch { /* ignore */ }
            state.jobWs = null;
            clearInterval(watchDog);

            invalidateHierarchy();

            const result = j.result || {};
            const m = result.materials || 0;
            const f = result.folders || {};
            setTimeout(() => {
                alert(`Импорт завершён!\n\nМатериалов: ${m}\nПапок создано: ${f.created || 0}\nУдалено: ${f.deleted || 0}`);
                closeModal('import');
                loadCollections();
            }, 300);
        } else if (msg.type === 'error') {
            els.importStatusText.innerText = `Ошибка: ${msg.message || 'unknown'}`;
            try { ws.close(); } catch { /* ignore */ }
            state.jobWs = null;
            clearInterval(watchDog);
            setTimeout(() => {
                alert(`Ошибка импорта: ${msg.message || 'unknown'}`);
                closeModal('import');
            }, 100);
        } else if (msg.type === 'cancelled') {
            const j = msg.data || msg;
            els.importProgress.style.width = `${j.progress || 0}%`;
            els.importStatusText.innerText = 'Отменено';
            try { ws.close(); } catch { /* ignore */ }
            state.jobWs = null;
            clearInterval(watchDog);
            invalidateHierarchy();
            setTimeout(() => {
                alert(`Импорт отменён.\n\n${j.details || ''}`);
                closeModal('import');
                loadJobs();
                loadCollections();
            }, 300);
        }
    };

    ws.onerror = (e) => {
        console.warn('[watchJob] WebSocket error, fallback to polling', e);
        try { ws.close(); } catch { /* ignore */ }
        state.jobWs = null;
        clearInterval(watchDog);
        pollJob(jobId);
    };

    ws.onclose = (ev) => {
        console.log('[watchJob] WebSocket closed', ev.code, ev.reason);
        state.jobWs = null;
        clearInterval(watchDog);
    };
}

/**
 * Best-effort POST to /hierarchy/<db>/invalidate. Errors are logged
 * but never rethrown — the import succeeded, the catalog just might
 * be slightly stale until the next refresh.
 */
export function invalidateHierarchy() {
    if (!state.activeCollection) return;
    fetch(`/hierarchy/${state.activeCollection}/invalidate`, { method: 'POST' })
        .then(() => console.log('✅ Кэш иерархии очищен'))
        .catch((e) => console.warn('⚠️ Не удалось очистить кэш иерархии:', e));
}
