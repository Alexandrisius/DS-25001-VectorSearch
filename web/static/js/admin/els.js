/**
 * Cached references to DOM elements used by the admin app.
 *
 * Resolved once at module load. Modules that need elements should import
 * this object rather than calling getElementById() themselves; that keeps
 * the wiring in one place and makes typos surface immediately.
 */

function $id(id) {
    return document.getElementById(id);
}

function $all(selector) {
    return document.querySelectorAll(selector);
}

export const els = {
    // --- auth screen ---
    loginScreen: $id('loginScreen'),
    adminApp: $id('adminApp'),
    authPassword: $id('authPassword'),
    authBtn: $id('authBtn'),
    authError: $id('authError'),

    // --- top nav ---
    navLinks: $all('.nav-item[data-view]'),
    pageTitle: $id('pageTitle'),
    headerActions: $id('headerActions'),
    logoutBtn: $id('logoutBtn'),
    contentBody: $id('contentBody'),

    // --- views ---
    views: {
        collections: $id('viewCollections'),
        jobs: $id('viewJobs'),
        data: $id('viewData'),
        settings: $id('viewSettings'),
    },

    // --- collections ---
    collectionsGrid: $id('collectionsGrid'),

    // --- data table ---
    dataTable: $id('dataTable'),
    dataTableHead: $id('dataTableHead'),
    dataTableBody: $id('dataTableBody'),
    scrollSentinel: $id('scrollSentinel'),
    infiniteScrollLoader: $id('infiniteScrollLoader'),

    // --- jobs view ---
    jobsTableBody: $id('jobsTableBody'),

    // --- modals ---
    modals: {
        config: $id('configModal'),
        import: $id('importModal'),
        create: $id('createModal'),
        addRecord: $id('addRecordModal'),
        deleteConfirm: $id('deleteConfirmModal'),
    },

    // --- delete confirmation ---
    deleteCollectionName: $id('deleteCollectionName'),
    deleteCollectionNameHint: $id('deleteCollectionNameHint'),
    deleteConfirmInput: $id('deleteConfirmInput'),
    confirmDeleteBtn: $id('confirmDeleteBtn'),

    // --- config form ---
    cfgName: $id('cfgName'),
    cfgCosine: $id('cfgCosine'),
    cfgRerank: $id('cfgRerank'),
    cfgVisible: $id('cfgVisible'),
    cfgRrfK: $id('cfgRrfK'),
    cfgMmrPool: $id('cfgMmrPool'),
    cfgRrfDense: $id('cfgRrfDense'),
    cfgRrfBm25: $id('cfgRrfBm25'),
    cfgMmrLambda: $id('cfgMmrLambda'),
    cfgConfidentMin: $id('cfgConfidentMin'),
    cfgUncertainMin: $id('cfgUncertainMin'),
    cfgFallbackCosine: $id('cfgFallbackCosine'),
    saveConfigBtn: $id('saveConfigBtn'),

    // --- create collection form ---
    newCollId: $id('newCollId'),
    newCollName: $id('newCollName'),
    newCollCosine: $id('newCollCosine'),
    newCollRerank: $id('newCollRerank'),
    newCollVisible: $id('newCollVisible'),
    createCollBtn: $id('createCollBtn'),

    // --- add record form ---
    newRecCode: $id('newRecCode'),
    newRecDesc: $id('newRecDesc'),
    saveRecBtn: $id('saveRecBtn'),

    // --- import wizard ---
    importTarget: $id('importTargetCollection'),
    pasteArea: $id('pasteArea'),
    mapCodeCols: $id('mapCodeCols'),
    mapDescCols: $id('mapDescCols'),
    mapHierarchyCols: $id('mapHierarchyCols'),
    codeSeparator: $id('codeSeparator'),
    descSeparator: $id('descSeparator'),
    codePreview: $id('codePreview'),
    descPreview: $id('descPreview'),
    hierarchyPreview: $id('hierarchyPreview'),
    importProgress: $id('importProgress'),
    importStatusText: $id('importStatusText'),
    importSteps: {
        paste: $id('importStep1'),
        mapping: $id('importStep2'),
        diff: $id('importStepDiff'),
        progress: $id('importStep3'),
    },
    importBtns: {
        back: $id('importBackBtn'),
        next: $id('importNextBtn'),
        compare: $id('importCompareBtn'),
        upload: $id('importUploadBtn'),
        apply: $id('importApplyBtn'),
    },

    // --- diff ---
    diffSummary: $id('diffSummary'),
    diffAddedCount: $id('diffAddedCount'),
    diffModifiedCount: $id('diffModifiedCount'),
    diffDeletedCount: $id('diffDeletedCount'),
    diffFoldersCount: $id('diffFoldersCount'),
    diffAddedBadge: $id('diffAddedBadge'),
    diffModifiedBadge: $id('diffModifiedBadge'),
    diffDeletedBadge: $id('diffDeletedBadge'),
    diffFoldersBadge: $id('diffFoldersBadge'),
    diffDeleteWarning: $id('diffDeleteWarning'),
    diffTableBody: $id('diffTableBody'),
    diffEmpty: $id('diffEmpty'),
    diffLoading: $id('diffLoading'),

    // --- preview ---
    previewTable: $id('previewTable'),
    previewHead: $id('previewHead'),
    previewBody: $id('previewBody'),
    previewCount: $id('previewCount'),
};
