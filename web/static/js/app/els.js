/**
 * Cached references to the app's DOM elements.
 */

function $id(id) {
    return document.getElementById(id);
}

const themeToggle = $id('themeToggle');
const themeIcon = themeToggle ? themeToggle.querySelector('i') : null;
const themeText = themeToggle ? themeToggle.querySelector('span') : null;
// (themeText is the visible label inside the toggle on desktop;
//  on mobile it is .visually-hidden so screen readers still
//  announce the state change.)

export const els = {
    // Search
    queryInput: $id('query'),
    clearBtn: $id('clearBtn'),
    searchBtn: $id('searchBtn'),
    resultsBody: $id('resultsBody'),
    errorContainer: $id('errorContainer'),
    statusInfo: $id('statusInfo'),
    processingInfo: $id('processingInfo'),
    processingTimeElement: $id('processingTime'),

    // Database select
    databaseSelect: $id('databaseSelect'),
    databaseOptions: $id('databaseOptions'),

    // Custom dropdown
    customSelectWrapper: $id('customSelect'),
    customSelectTrigger: document.querySelector('#customSelect .custom-select-trigger'),
    customOptionsContainer: $id('customOptions'),
    customSelectValue: $id('customSelectValue'),

    // Theme
    themeToggle,
    themeIcon,
    themeText,

    // Sidebar
    catalogSidebar: $id('catalogSidebar'),
    sidebarToggle: $id('sidebarToggle'),
    sidebarResizer: $id('sidebarResizer'),
    hierarchyTreeEl: $id('hierarchyTree'),
    totalCategoriesEl: $id('totalCategories'),
    totalItemsEl: $id('totalItems'),
    appLayout: $id('appLayout'),

    // Multi-select
    multiSelectHint: $id('multiSelectHint'),
    selectedCountEl: $id('selectedCount'),
    clearSelectionBtn: $id('clearSelectionBtn'),

    // Catalog search
    catalogSearchInput: $id('catalogSearchInput'),
    catalogSearchClear: $id('catalogSearchClear'),
    catalogSearchResults: $id('catalogSearchResults'),
    filterIndicator: $id('filterIndicator'),

    // Sticky breadcrumbs
    sidebarContent: $id('sidebarContent'),
    stickyBreadcrumbs: $id('stickyBreadcrumbs'),

    // Catalog refresh / collapse buttons (read by sidebar.js)
    collapseAllBtn: $id('collapseAllBtn'),
    refreshCatalogBtn: $id('refreshCatalogBtn'),
};

/**
 * Map a status-keyword to the matching `.status-info--*` class on the
 * status info element. Replaces the previous `style.color` assignments
 * scattered through search.js and results.js. Also clears any other
 * state class so the element only ever has one color modifier.
 */
export function setStatusInfoColor(kind) {
    if (!els.statusInfo) return;
    const variants = ['primary', 'danger', 'warning', 'success'];
    for (const v of variants) {
        els.statusInfo.classList.remove(`status-info--${v}`);
    }
    if (kind && variants.includes(kind)) {
        els.statusInfo.classList.add(`status-info--${kind}`);
    }
}
