/**
 * Shared constants.
 * Single source of truth for status labels, storage keys, and config values
 * duplicated across admin/ and app/.
 */

/** Status labels for background jobs (import, reindex, ...). */
export const JOB_STATUS_LABELS = Object.freeze({
    pending: 'Ожидание',
    processing: 'Обработка',
    completed: 'Завершено',
    error: 'Ошибка',
    cancelled: 'Отменено',
});

/** Background-job status value to a small CSS class suffix. */
export const JOB_STATUS_CLASS = Object.freeze({
    pending: 'pending',
    processing: 'processing',
    completed: 'completed',
    error: 'error',
    cancelled: 'cancelled',
});

/** localStorage / sessionStorage keys. Centralised so tests and refactors
 *  can grep a single place. */
export const STORAGE_KEYS = Object.freeze({
    adminToken: 'adminToken',
    adminColumnWidths: 'adminColumnWidths',
    importModalWidth: 'importModalWidth',
    adminMobileWarningDismissed: 'adminMobileWarningDismissed',
    theme: 'theme',
    sidebarWidth: 'sidebarWidth',
    catalogSidebarCollapsed: 'catalogSidebarCollapsed',
});

/** Default debounce delay for search inputs (ms). */
export const SEARCH_DEBOUNCE_MS = 300;

/** Hysteresis threshold for sticky breadcrumbs (px). */
export const STICKY_HYSTERESIS = 20;

/** Long-press duration for mobile tree interactions (ms). */
export const LONG_PRESS_DURATION = 500;

/** Max finger movement (px) before a long-press is cancelled. */
export const LONG_PRESS_MOVE_THRESHOLD = 10;

/** Pagination page size for the admin data table. */
export const DATA_TABLE_PAGE_SIZE = 100;

/** WebSocket timeout for job watchdogs (ms). */
export const JOB_WATCHDOG_TIMEOUT = 60_000;

/** Polling interval for fallback job tracking (ms). */
export const JOB_POLL_INTERVAL = 2_000;

/** Polling interval for in-progress job progress sync (ms). */
export const JOB_PROGRESS_INTERVAL = 1_500;
