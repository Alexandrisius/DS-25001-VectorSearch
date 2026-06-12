/**
 * Modal open/close + focus management + resize helpers.
 *
 * Focus management (trap + restore) lives in shared/focus-trap.js and
 * is enabled by adding the `data-trap-focus` attribute to a
 * `.modal-overlay`.
 *
 * Resize is specific to the import modal (other modals are small).
 */

import { state } from './state.js';
import { els } from './els.js';
import { STORAGE_KEYS } from '../shared/constants.js';
import { trapFocus, releaseFocus } from '../shared/focus-trap.js';

/**
 * Open a modal by its key in els.modals. If the modal has the
 * `data-trap-focus` attribute, focus is trapped inside it.
 *
 * @param {'config'|'import'|'create'|'addRecord'|'deleteConfirm'} name
 */
export function openModal(name) {
    const modal = els.modals[name];
    if (!modal) return;
    modal.classList.add('active');
    if (modal.hasAttribute('data-trap-focus')) {
        trapFocus(modal);
    }
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

    releaseFocus();
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
            releaseFocus();
        });
    });

    // Click on the backdrop (but not the modal-window) closes the modal.
    document.querySelectorAll('.modal-overlay').forEach((overlay) => {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                overlay.classList.remove('active');
                releaseFocus();
            }
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
            document.body.classList.add('is-resizing');
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
        document.body.classList.remove('is-resizing');
        try {
            localStorage.setItem(STORAGE_KEYS.importModalWidth, String(modalWindow.offsetWidth));
        } catch {
            /* storage unavailable */
        }
    });
}
