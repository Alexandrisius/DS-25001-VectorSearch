/**
 * App state.
 *
 * Three groups of mutable state:
 *   - app: search-related (current query, results, database list)
 *   - filter: multi-select category filter (selected paths, current)
 *   - catalog: tree rendering state (lazy-loaded paths, in-flight flag,
 *     sticky-breadcrumb hysteresis)
 *
 * State is module-private (live inside the module) and exposed via
 * getters / setters that re-export the underlying variables.
 */

import { STORAGE_KEYS } from '../shared/constants.js';

/* ------------------------------------------------------------------ */
/*  Search state                                                       */
/* ------------------------------------------------------------------ */

let currentDatabase = 'ksr_main';
/** @type {Array<{name: string, description: string, record_count: number, last_updated?: string, phase4?: Object}>} */
let databases = [];
let currentQuery = '';
/** @type {Array<{code: string, description: string, rank: number, reranker_score: number, cosine_similarity: number, material_name?: string, category_path?: string}>} */
let currentResults = [];

export const appState = {
    get currentDatabase() { return currentDatabase; },
    set currentDatabase(v) { currentDatabase = v; },

    get databases() { return databases; },
    set databases(v) { databases = v; },

    get currentQuery() { return currentQuery; },
    set currentQuery(v) { currentQuery = v; },

    get currentResults() { return currentResults; },
    set currentResults(v) { currentResults = v; },
};

/* ------------------------------------------------------------------ */
/*  Filter state (sidebar multi-select)                               */
/* ------------------------------------------------------------------ */

let selectedPaths = [];
let currentFilterPath = null;
let currentFilterLevel = null;
let sidebarCollapsed = false;
let sidebarWidth = (() => {
    try {
        return parseInt(localStorage.getItem(STORAGE_KEYS.sidebarWidth) || '500', 10);
    } catch {
        return 500;
    }
})();

/** Touch / long-press state for the tree on mobile devices. */
let longPressTimer = null;
let longPressTriggered = false;
let touchStartX = 0;
let touchStartY = 0;

export const filterState = {
    get selectedPaths() { return selectedPaths; },
    set selectedPaths(v) { selectedPaths = v; },

    get currentFilterPath() { return currentFilterPath; },
    set currentFilterPath(v) { currentFilterPath = v; },

    get currentFilterLevel() { return currentFilterLevel; },
    set currentFilterLevel(v) { currentFilterLevel = v; },

    get sidebarCollapsed() { return sidebarCollapsed; },
    set sidebarCollapsed(v) { sidebarCollapsed = v; },

    get sidebarWidth() { return sidebarWidth; },
    set sidebarWidth(v) { sidebarWidth = v; },

    get longPressTimer() { return longPressTimer; },
    set longPressTimer(v) { longPressTimer = v; },

    get longPressTriggered() { return longPressTriggered; },
    set longPressTriggered(v) { longPressTriggered = v; },

    get touchStartX() { return touchStartX; },
    set touchStartX(v) { touchStartX = v; },

    get touchStartY() { return touchStartY; },
    set touchStartY(v) { touchStartY = v; },
};

/* ------------------------------------------------------------------ */
/*  Catalog tree state                                                 */
/* ------------------------------------------------------------------ */

/** @type {Set<string>} Cache of already-loaded paths (for lazy loading). */
const loadedPaths = new Set();
let isHierarchyLoading = false;
/** @type {string|null} - last computed sticky-breadcrumb key (hysteresis). */
let lastStickyPath = null;

export const catalogState = {
    get loadedPaths() { return loadedPaths; },
    get isHierarchyLoading() { return isHierarchyLoading; },
    set isHierarchyLoading(v) { isHierarchyLoading = v; },
    get lastStickyPath() { return lastStickyPath; },
    set lastStickyPath(v) { lastStickyPath = v; },
};
