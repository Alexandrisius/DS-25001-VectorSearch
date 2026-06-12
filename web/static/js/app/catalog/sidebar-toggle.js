/**
 * Catalog sidebar: toggle, resize, refresh, collapse-all.
 *
 * The original sidebar.js mixed "permanent" UI plumbing (toggle,
 * resize, width restore) with "command" buttons (refresh, collapse).
 * Split out of the original sidebar.js (182 LoC) for module size
 * management.
 *
 * - initCatalogSidebar:        one-time wiring (toggle, restore state).
 * - toggleSidebar / applySidebarWidth / updateToggleButton:  public
 *   API used by tree-handlers.js and the navigation module.
 * - initSidebarResizer:       drag-to-resize handle.
 */

import { els } from '../els.js';
import { appState, filterState } from '../state.js';
import { STORAGE_KEYS } from '../../shared/constants.js';
import { clearAllSelections } from '../filter.js';

let savedWidth = 500;
try {
    savedWidth = parseInt(localStorage.getItem(STORAGE_KEYS.sidebarWidth) || '500', 10);
} catch {
    savedWidth = 500;
}

/**
 * Wire up sidebar controls. Called once at bootstrap.
 */
export function initCatalogSidebar() {
    if (!els.catalogSidebar || !els.sidebarToggle) {
        console.warn('⚠️ Элементы sidebar не найдены');
        return;
    }

    els.sidebarToggle.addEventListener('click', toggleSidebar);
    initSidebarResizer();

    els.clearSelectionBtn?.addEventListener('click', clearAllSelections);

    // Restore collapsed state.
    let saved = 'false';
    try {
        saved = localStorage.getItem(STORAGE_KEYS.catalogSidebarCollapsed) || 'false';
    } catch {
        saved = 'false';
    }
    if (saved === 'true') {
        filterState.sidebarCollapsed = true;
        els.catalogSidebar.classList.add('collapsed');
        els.appLayout?.classList.remove('sidebar-open');
        els.appLayout?.classList.add('sidebar-collapsed');
        updateToggleButton();
    } else {
        applySidebarWidth();
    }
}

/**
 * Toggle the sidebar open / closed and persist the new state.
 */
export function toggleSidebar() {
    filterState.sidebarCollapsed = !filterState.sidebarCollapsed;
    els.catalogSidebar.classList.toggle('collapsed', filterState.sidebarCollapsed);

    if (filterState.sidebarCollapsed) {
        els.appLayout?.classList.remove('sidebar-open');
        els.appLayout?.classList.add('sidebar-collapsed');
        els.catalogSidebar.style.width = '';
    } else {
        els.appLayout?.classList.remove('sidebar-collapsed');
        els.appLayout?.classList.add('sidebar-open');
        applySidebarWidth();
    }
    updateToggleButton();
    try {
        localStorage.setItem(STORAGE_KEYS.catalogSidebarCollapsed, String(filterState.sidebarCollapsed));
    } catch {
        /* storage unavailable */
    }
}

/**
 * Initialise the drag-resize handle for the sidebar.
 */
function initSidebarResizer() {
    if (!els.sidebarResizer) return;

    let isResizing = false;
    let startX = 0;
    let startWidth = 0;

    els.sidebarResizer.addEventListener('mousedown', (e) => {
        isResizing = true;
        startX = e.clientX;
        startWidth = els.catalogSidebar.offsetWidth;
        els.sidebarResizer.classList.add('active');
        document.body.classList.add('is-resizing');
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const delta = e.clientX - startX;
        const newWidth = Math.max(350, Math.min(800, startWidth + delta));
        filterState.sidebarWidth = newWidth;
        applySidebarWidth();
    });

    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            els.sidebarResizer.classList.remove('active');
            document.body.classList.remove('is-resizing');
            try {
                localStorage.setItem(STORAGE_KEYS.sidebarWidth, String(filterState.sidebarWidth));
            } catch {
                /* storage unavailable */
            }
        }
    });
}

/**
 * Apply the saved width to the sidebar element and to the
 * `--sidebar-width` CSS custom property.
 */
export function applySidebarWidth() {
    if (filterState.sidebarCollapsed) return;
    if (els.catalogSidebar) {
        els.catalogSidebar.style.width = filterState.sidebarWidth + 'px';
    }
    document.documentElement.style.setProperty('--sidebar-width', filterState.sidebarWidth + 'px');
}

/**
 * Update the toggle button's icon and text to reflect the current
 * collapse state.
 */
export function updateToggleButton() {
    if (!els.sidebarToggle) return;
    const icon = els.sidebarToggle.querySelector('i');
    const text = els.sidebarToggle.querySelector('.toggle-text');
    if (filterState.sidebarCollapsed) {
        icon?.classList.remove('fa-angles-left');
        icon?.classList.add('fa-angles-right');
        if (text) text.textContent = 'Развернуть';
    } else {
        icon?.classList.remove('fa-angles-right');
        icon?.classList.add('fa-angles-left');
        if (text) text.textContent = 'Свернуть';
    }
}
