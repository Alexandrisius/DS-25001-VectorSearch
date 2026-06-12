/**
 * Modal open/close + resize helpers.
 *
 * Resize is specific to the import modal (other modals are small).
 */

import { state } from './state.js';
import { els } from './els.js';
import { STORAGE_KEYS } from '../shared/constants.js';

/**
 * Open a modal by its key in els.modals.
 *
 * @param {'config'|'import'|'create'|'addRecord'|'deleteConfirm'} name
 */
export function openModal(name) {
    if (els.modals[name]) els.modals[name].classList.add('active');
}

/**
 * Close a modal. When closing the import modal, also stop any
 * background-job tracking intervals and close the WebSocket to free
 * server resources — without this, closing the modal while a job
 * runs would leave dangling pollers (the previous code only stopped
 * `state.jobInterval`, leaking the WebSocket).
 *
 * @param {'config'|'import'|'create'|'addRecord'|'deleteConfirm'} name
 */
export function closeModal(name) {
    if (els.modals[name]) els.modals[name].classList.remove('active');

    if (name === 'import') {
        if (state.jobInterval) {
            clearInterval(state.jobInterval);
            state.jobInterval = null;
        }
        if (state.jobWs) {
            try { state.jobWs.close(); } catch { /* already closed */ }
            state.jobWs = null;
        }
    }
}

/**
 * Wire up close buttons (.modal-close, .modal-close-btn) — generic
 * delegated handler so the markup doesn't need per-modal wiring.
 */
export function initModals() {
    document.querySelectorAll('.modal-close, .modal-close-btn').forEach((btn) => {
        btn.addEventListener('click', function () {
            const modal = this.closest('.modal-overlay');
            if (modal) modal.classList.remove('active');
        });
    });
}

/**
 * Drag-resize the import modal horizontally via the `.modal-resizer`
 * handles. Width is persisted in localStorage.
 */
export function initModalResize() {
    const modalWindow = document.getElementById('importModalWindow');
    if (!modalWindow) return;

    const resizers = modalWindow.querySelectorAll('.modal-resizer');
    if (resizers.length === 0) return;

    let isResizing = false;
    let startX = 0;
    let startWidth = 0;
    let currentResizer = null;

    // Restore saved width (sanity-check the value).
    const savedWidth = localStorage.getItem(STORAGE_KEYS.importModalWidth);
    if (savedWidth) {
        const width = parseInt(savedWidth, 10);
        if (width >= 800 && width <= window.innerWidth * 0.95) {
            modalWindow.style.width = width + 'px';
        }
    }

    resizers.forEach((resizer) => {
        resizer.addEventListener('mousedown', (e) => {
            isResizing = true;
            startX = e.clientX;
            startWidth = modalWindow.offsetWidth;
            currentResizer = resizer;
            resizer.classList.add('active');
            document.body.style.cursor = 'ew-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const direction = currentResizer.dataset.direction;
        let delta = e.clientX - startX;
        // For the left handle invert the delta. Either way, double the
        // movement so the modal grows/shrinks symmetrically.
        if (direction === 'left') delta = -delta;
        const newWidth = Math.max(800, Math.min(window.innerWidth * 0.95, startWidth + delta * 2));
        modalWindow.style.width = newWidth + 'px';
    });

    document.addEventListener('mouseup', () => {
        if (!isResizing) return;
        isResizing = false;
        if (currentResizer) currentResizer.classList.remove('active');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        try {
            localStorage.setItem(STORAGE_KEYS.importModalWidth, String(modalWindow.offsetWidth));
        } catch {
            /* storage unavailable */
        }
    });
}
