/**
 * Admin entry point.
 *
 * Wires every module together. Each `init*` function installs its
 * document-level listeners; per-view modules (data-table, import
 * wizard) set up their own state lazily when the user navigates
 * into them.
 *
 * IMPORTANT: import order matters. Modules with no internal
 * dependencies are imported first, then modules that depend on them.
 * Cycles are avoided — if you find a cycle, the right fix is to
 * extract the shared concept into its own module.
 */

// --- core ---
import { initAuth } from './auth.js';
import { initNavigation } from './navigation.js';
import { initModals, initModalResize } from './modals.js';
import { checkMobileDevice } from './mobile.js';

// --- collections ---
import { initCollectionsCardHandler } from './collections/list.js';
import { initConfigForm } from './collections/config.js';
import { initCreateCollection } from './collections/create.js';
import { initDeleteHandlers } from './collections/delete.js';

// --- data table ---
import { initStatusDropdowns } from './data-table/status.js';
import { initDeleteRecordDelegation } from './data-table/delete-record.js';
import { initAddRecord } from './data-table/add-record.js';
import { initSorting } from './data-table/sort.js';

// --- import wizard ---
import { initImportWizard } from './import/wizard.js';
import { initJobStopHandler } from './import/jobs-list.js';

// --- cleaning rules ---
import { initCleaningRulesEvents } from './cleaning-rules/events.js';
import { CleaningRulesModule } from './cleaning-rules/list.js';

// --- settings ---
import { initSettingsPage } from './settings/statuses-form.js';
import { loadStatuses } from './settings/statuses-list.js';
import {
    initOpenRouterSettings,
    loadOpenRouterSettings,
} from './settings/openrouter.js';

/**
 * Bootstrap on DOMContentLoaded.
 */
document.addEventListener('DOMContentLoaded', () => {
    // --- mobile warning (independent of auth) ---
    checkMobileDevice();

    // --- core ---
    initAuth();
    initNavigation();
    initModals();
    initModalResize();

    // --- settings (load regardless of view) ---
    initOpenRouterSettings();
    loadOpenRouterSettings();
    initSettingsPage();
    initCleaningRulesEvents();

    // --- collections ---
    initCollectionsCardHandler();
    initConfigForm();
    initCreateCollection();
    initDeleteHandlers();

    // --- data table ---
    initStatusDropdowns();
    initDeleteRecordDelegation();
    initAddRecord();
    initSorting();

    // --- import wizard ---
    initImportWizard();
    initJobStopHandler();

    // --- status defaults ---
    loadStatuses();

    // --- cleaning rules data ---
    CleaningRulesModule.load();
});
