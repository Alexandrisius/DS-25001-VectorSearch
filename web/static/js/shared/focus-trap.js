/**
 * Focus-trap and escape-to-close helper for modals.
 *
 * WCAG 2.1 §2.4.3 (focus order): when a modal opens, focus moves
 * into the modal; while the modal is open, Tab and Shift+Tab cycle
 * only through focusable elements inside it. Escape closes the
 * topmost modal. On close, focus restores to the element that opened
 * the modal.
 *
 * The trap is opt-in: the modal element must have
 * `data-trap-focus` for us to install on it.
 */

const FOCUSABLE = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled]):not([type="hidden"])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
].join(',');

const trapped = new WeakSet();
let lastFocused = null;
let currentTrap = null;

/**
 * Wrap focus inside `el`. Idempotent — safe to call on the same
 * element twice.
 */
export function trapFocus(el) {
    if (!el || trapped.has(el)) return;
    trapped.add(el);
    lastFocused = document.activeElement;
    currentTrap = el;

    document.addEventListener('keydown', onKeydown, true);
}

/**
 * Release the active focus trap. Idempotent.
 */
export function releaseFocus() {
    document.removeEventListener('keydown', onKeydown, true);
    if (lastFocused && typeof lastFocused.focus === 'function') {
        try { lastFocused.focus(); } catch { /* element gone */ }
    }
    lastFocused = null;
    currentTrap = null;
}

function onKeydown(e) {
    if (!currentTrap) return;

    // Escape closes the topmost modal
    if (e.key === 'Escape') {
        e.preventDefault();
        closeTopmostModal();
        return;
    }

    // Tab cycling
    if (e.key !== 'Tab') return;
    const focusables = Array.from(currentTrap.querySelectorAll(FOCUSABLE))
        .filter((n) => n.offsetParent !== null || n === document.activeElement);
    if (focusables.length === 0) {
        e.preventDefault();
        return;
    }
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const active = document.activeElement;

    if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
    } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
    }
}

function closeTopmostModal() {
    const modals = document.querySelectorAll('.modal-overlay.active');
    if (modals.length === 0) return;
    const top = modals[modals.length - 1];
    top.classList.remove('active');
    // Don't release focus here — the per-modal close handler should
    // call releaseFocus() (or the next modal opening will reset it).
}
