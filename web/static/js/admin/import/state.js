/**
 * Import wizard state.
 *
 * Lives in its own module (not in admin/state.js) because:
 *   - it has a different lifecycle (reset on every openImport())
 *   - it would otherwise bloat the global admin state
 *
 * Three concerns are kept here:
 *   - importData: the pasted / Excel-loaded data + mapping selections
 *   - diffData: the result of the diff analysis (added/modified/deleted)
 *   - diffActiveTab: which diff tab is currently visible
 */

/**
 * The wizard's transient state. Mutated in place by the various
 * wizard modules; reset by openImport() when the modal opens.
 */
export const importData = {
    raw: [],
    headers: [],
    codeSelection: {},
    descSelection: {},
    hierarchySelection: {},
    codeSeparator: '.',
    descSeparator: ' ',
    // Excel-specific fields, populated when an .xlsx/.xls file is uploaded.
    excelFile: null,
    excelData: null,
    cacheKey: null,
    totalRows: null,
};

/**
 * Diff result. Populated by performDiffAnalysis(); rendered by
 * renderDiffTable() / renderFoldersDiffTable().
 */
export const diffData = {
    added: [],
    modified: [],
    deleted: [],
    unchanged: 0,
    existingRecords: {},
    folderChanges: {
        added: [],
        modified: [],
        deleted: [],
    },
    existingFolders: {},
};

/** Currently visible diff tab. */
export const diffActiveTab = { current: 'added' };

/**
 * Reset wizard state to its initial values. Called by openImport().
 */
export function resetImportState() {
    importData.raw = [];
    importData.headers = [];
    importData.codeSelection = {};
    importData.descSelection = {};
    importData.hierarchySelection = {};
    importData.codeSeparator = '.';
    importData.descSeparator = ' ';
    importData.excelFile = null;
    importData.excelData = null;
    importData.cacheKey = null;
    importData.totalRows = null;

    diffData.added = [];
    diffData.modified = [];
    diffData.deleted = [];
    diffData.unchanged = 0;
    diffData.existingRecords = {};
    diffData.folderChanges = { added: [], modified: [], deleted: [] };
    diffData.existingFolders = {};

    diffActiveTab.current = 'added';
}
