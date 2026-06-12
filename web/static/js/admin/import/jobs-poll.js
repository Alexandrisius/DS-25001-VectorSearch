/**
 * Polling-based job tracking, used as a fallback for watchJob's
 * WebSocket subscription and as a one-shot poll for the apply-diff
 * flow.
 *
 * Two functions:
 *   - pollJob: continuous poll that runs until the job completes,
 *     errors out, or is cancelled. Used by the WebSocket fallback path.
 *   - pollJobUntilComplete: one-shot Promise wrapper used by
 *     applyDiffChanges() (run-apply.js) to map the inner job's
 *     0-100% progress onto a sub-range of the outer 0-100% bar.
 *
 * Split out of the original jobs.js for module size management.
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { authFetch } from '../../shared/api.js';
import { JOB_STATUS_LABELS, JOB_POLL_INTERVAL, JOB_PROGRESS_INTERVAL } from '../../shared/constants.js';
import { closeModal } from '../modals.js';
import { loadCollections } from '../collections/list.js';
import { loadJobs } from './jobs-list.js';
import { invalidateHierarchy } from './jobs-watch.js';

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
 * One-shot polling used by the diff apply flow, with a progress bar
 * that is mapped onto a sub-range of the overall 0-100% bar.
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
