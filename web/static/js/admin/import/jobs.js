/**
 * Background-job tracking shared between the import wizard and the
 * "Background jobs" view.
 *
 * Two strategies are supported:
 *   - watchJob: WebSocket subscription with auto-reconnect via polling
 *   - pollJobUntilComplete: one-shot polling used by the diff apply flow
 *
 * Both update a single status/progress pair (els.importProgress /
 * els.importStatusText) so the import modal can render the live state.
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { authFetch } from '../../shared/api.js';
import {
    JOB_STATUS_LABELS,
    JOB_WATCHDOG_TIMEOUT,
    JOB_POLL_INTERVAL,
    JOB_PROGRESS_INTERVAL,
} from '../../shared/constants.js';
import { loadCollections } from '../collections/list.js';
import { closeModal } from '../modals.js';

/**
 * Public entry-point used by the navigation module: keep the "Background
 * jobs" view in sync with the server by polling every 3s while the
 * user is on that view.
 */
export function startJobPoller() {
    setInterval(() => {
        if (state.currentView === 'jobs') loadJobs();
    }, 3_000);
}

/**
 * Render the jobs list. Each row gets a data-job-id so the click handler
 * can stop the job without inline onclick.
 */
export async function loadJobs() {
    try {
        const res = await authFetch('/admin/jobs');
        const data = await res.json();
        const jobs = data.jobs || [];

        if (!els.jobsTableBody) return;

        els.jobsTableBody.innerHTML = jobs.map((j) => {
            const canStop = j.status === 'pending' || j.status === 'processing';
            const createdAt = j.created_at
                ? new Date(j.created_at).toLocaleString('ru-RU')
                : '—';
            const stopButton = canStop
                ? `<button class="btn btn-danger btn-stop-job" data-job-id="${j.id}" style="padding: 4px 8px; font-size: 0.8rem;" title="Остановить"><i class="fas fa-stop"></i></button>`
                : '';
            return `
            <tr>
                <td style="font-family:monospace; font-size:0.8rem">${j.id.slice(0, 8)}...</td>
                <td>${j.type === 'import_batch' ? 'Импорт' : j.type}</td>
                <td><span class="status-badge status-${j.status}">${JOB_STATUS_LABELS[j.status] || j.status}</span></td>
                <td>
                    <div class="progress-bar-container" style="width: 100px; height: 6px;">
                        <div class="progress-bar-fill" style="width: ${j.progress || 0}%"></div>
                    </div>
                    <small>${j.progress || 0}% ${j.total ? `/ ${j.total}` : ''}</small>
                </td>
                <td title="${j.details || ''}">${j.details || '—'}</td>
                <td>${createdAt}</td>
                <td>${stopButton}</td>
            </tr>
        `;
        }).join('');
    } catch (e) {
        if (e.message !== 'Unauthorized') {
            console.error('Failed to load jobs:', e);
        }
    }
}

/**
 * Stop button click handler — installed once on document load.
 * Wires the buttons rendered by loadJobs().
 */
export function initJobStopHandler() {
    document.addEventListener('click', async (e) => {
        const btn = e.target.closest('.btn-stop-job');
        if (!btn) return;
        const jobId = btn.dataset.jobId;
        if (!jobId) return;
        if (!confirm('Вы уверены, что хотите остановить эту задачу?')) return;
        try {
            const res = await authFetch(`/admin/jobs/${jobId}/stop`, { method: 'POST' });
            if (res.ok) {
                loadJobs();
            } else {
                const err = await res.json().catch(() => ({}));
                alert('Ошибка: ' + (err.detail || 'Не удалось остановить задачу'));
            }
        } catch (e) {
            alert('Ошибка связи с сервером');
        }
    });
}

/**
 * Subscribe to a job's progress via WebSocket. Falls back to pollJob() on
 * any error or after a 60s watchdog timeout with no updates.
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
    }, 10_000);

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
 * Polling fallback used when the WebSocket is unavailable.
 *
 * @param {string} jobId
 */
export function pollJob(jobId) {
    if (state.jobInterval) clearInterval(state.jobInterval);
    els.importStatusText.innerText = 'В очереди...';
    els.importProgress.style.width = '0%';

    state.jobInterval = setInterval(async () => {
        try {
            const res = await authFetch('/admin/jobs');
            const data = await res.json();
            const jobs = data.jobs || [];
            const job = jobs.find((j) => j.id === jobId);

            if (job) {
                els.importProgress.style.width = `${job.progress || 0}%`;
                els.importStatusText.innerText = `${JOB_STATUS_LABELS[job.status] || job.status} (${job.progress || 0}%) — ${job.details || ''}`;

                if (job.status === 'completed') {
                    clearInterval(state.jobInterval);
                    state.jobInterval = null;
                    invalidateHierarchy();
                    setTimeout(() => {
                        const m = job.result?.materials || 0;
                        const f = job.result?.folders || {};
                        alert(`Импорт завершён!\n\nМатериалов: ${m}\nПапок создано: ${f.created || 0}`);
                        closeModal('import');
                        loadCollections();
                    }, 500);
                } else if (job.status === 'error') {
                    clearInterval(state.jobInterval);
                    state.jobInterval = null;
                    alert(`Ошибка: ${job.error || 'unknown'}`);
                    closeModal('import');
                } else if (job.status === 'cancelled') {
                    clearInterval(state.jobInterval);
                    state.jobInterval = null;
                    alert('Импорт отменен пользователем');
                    closeModal('import');
                }
            }
        } catch (e) {
            if (e.message === 'Unauthorized') {
                clearInterval(state.jobInterval);
                state.jobInterval = null;
            }
        }
    }, JOB_POLL_INTERVAL);
}

/**
 * One-shot polling used by the diff apply flow, with a progress bar that
 * is mapped onto a sub-range of the overall 0-100% bar.
 *
 * @param {string} jobId
 * @param {number} progressStart - 0-100
 * @param {number} progressEnd - 0-100
 * @returns {Promise<void>}
 */
export function pollJobUntilComplete(jobId, progressStart, progressEnd) {
    return new Promise((resolve, reject) => {
        const interval = setInterval(async () => {
            try {
                const res = await authFetch('/admin/jobs');
                const jobs = await res.json();
                const job = jobs.find((j) => j.id === jobId);

                if (job) {
                    const scaledProgress =
                        progressStart + (job.progress / 100) * (progressEnd - progressStart);
                    els.importProgress.style.width = `${scaledProgress}%`;
                    els.importStatusText.innerText = `${JOB_STATUS_LABELS[job.status] || job.status} (${job.progress}%)`;

                    if (job.status === 'completed') {
                        clearInterval(interval);
                        resolve();
                    } else if (job.status === 'error') {
                        clearInterval(interval);
                        reject(new Error(job.error || 'Ошибка обработки'));
                    } else if (job.status === 'cancelled') {
                        clearInterval(interval);
                        reject(new Error('Задача отменена пользователем'));
                    }
                }
            } catch (e) {
                if (e.message === 'Unauthorized') {
                    clearInterval(interval);
                    reject(e);
                }
            }
        }, JOB_PROGRESS_INTERVAL);
    });
}

/**
 * Best-effort POST to /hierarchy/<db>/invalidate. Errors are logged
 * but never rethrown — the import succeeded, the catalog just might
 * be slightly stale until the next refresh.
 */
function invalidateHierarchy() {
    if (!state.activeCollection) return;
    fetch(`/hierarchy/${state.activeCollection}/invalidate`, { method: 'POST' })
        .then(() => console.log('✅ Кэш иерархии очищен'))
        .catch((e) => console.warn('⚠️ Не удалось очистить кэш иерархии:', e));
}
