/**
 * Background-job list UI.
 *
 * Public entry-point used by the navigation module: keep the
 * "Background jobs" view in sync with the server by polling every
 * 3s while the user is on that view.
 *
 * Two functions: startJobPoller (kicks off the interval) and
 * loadJobs (fetches the list and re-renders). initJobStopHandler
 * wires the per-row stop button via delegation.
 *
 * Split out of the original jobs.js for module size management.
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { authFetch } from '../../shared/api.js';
import { JOB_STATUS_LABELS } from '../../shared/constants.js';
import { loadCollections } from '../collections/list.js';

let pollTimer = null;

/**
 * Start the background polling. Stays running for the lifetime of
 * the page; only refreshes the table when the user is on the jobs
 * view.
 */
export function startJobPoller() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => {
        if (state.currentView === 'jobs') loadJobs();
    }, 3000);
}

/**
 * Render the jobs list. Each row gets a `data-job-id` so the click
 * handler can stop the job without inline onclick.
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
                ? `<button class="btn btn-danger btn-stop-job" data-job-id="${j.id}" title="Остановить"><i class="fas fa-stop"></i></button>`
                : '';
            return `
            <tr>
                <td class="job-id">${j.id.slice(0, 8)}...</td>
                <td>${j.type === 'import_batch' ? 'Импорт' : j.type}</td>
                <td><span class="status-badge status-${j.status}">${JOB_STATUS_LABELS[j.status] || j.status}</span></td>
                <td>
                    <div class="job-progress">
                        <div class="job-progress-bar">
                            <div class="job-progress-bar-fill" style="width: ${j.progress || 0}%"></div>
                        </div>
                        <small>${j.progress || 0}% ${j.total ? `/ ${j.total}` : ''}</small>
                    </div>
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
