/**
 * Admin global state.
 *
 * Exposed as a single object that mutates in place. Modules import it and
 * read/write its fields directly. Importing this module is cheap; the
 * object literal is evaluated once at module load.
 */

/** @type {string|null} JWT token restored from localStorage. */
const initialToken = (() => {
    try {
        return localStorage.getItem('adminToken');
    } catch {
        return null;
    }
})();

/** @type {Object} Column widths persisted in localStorage. */
const initialColumnWidths = (() => {
    try {
        return JSON.parse(localStorage.getItem('adminColumnWidths') || '{}');
    } catch {
        return {};
    }
})();

/**
 * Global admin state. Fields grouped by concern.
 *
 * Note: importData and diffData are owned by the import wizard module
 * (admin/import/state.js) and reset by openImport(); keeping them out
 * of this object keeps the responsibilities clean.
 */
export const state = {
    // --- auth ---
    token: initialToken,

    // --- navigation / collections ---
    currentView: 'collections',            // 'collections' | 'jobs' | 'data' | 'settings'
    collections: [],
    activeCollection: null,

    // --- data table ---
    dataOffset: null,                      // pagination token
    dataRows: [],
    sortColumn: null,
    sortDirection: 'asc',
    pathLevelColumns: [],
    hasFullDescription: false,
    columnWidths: initialColumnWidths,
    isLoadingData: false,                  // infinite-scroll lock
    scrollObserver: null,                  // IntersectionObserver for sentinel

    // --- background job tracking ---
    // jobWs / jobInterval are owned by the import jobs module, but we keep
    // a small reference here so closeModal('import') can stop them.
    jobWs: null,
    jobInterval: null,
    jobPoller: null,                       // interval id for the jobs-view poller (see startJobPoller)

    // --- records / statuses ---
    statuses: [],
    defaultStatus: 'active',

    // --- cleaning rules ---
    cleaningRules: [],
};

/**
 * Persist column widths to localStorage.
 */
export function persistColumnWidths() {
    try {
        localStorage.setItem('adminColumnWidths', JSON.stringify(state.columnWidths));
    } catch {
        /* storage unavailable */
    }
}
