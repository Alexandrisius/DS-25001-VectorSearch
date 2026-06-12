/**
 * Import wizard: open/close, step navigation, top-level wiring.
 *
 * The wizard has four steps:
 *   1. paste   — pick source (paste / Excel), parse data
 *   2. mapping — pick which columns map to code / desc / hierarchy
 *   3. diff    — preview added/modified/deleted changes
 *   4. progress — import running, polls/watches the background job
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { openModal } from '../modals.js';
import { importData, resetImportState } from './state.js';
import { processPastedData } from './paste.js';
import { resetExcelUploadUI } from './excel.js';
import { initImportSourceTabs } from './source-tabs.js';
import { initExcelUpload } from './excel.js';
import { initDiffTabs } from './diff/tabs.js';
import { validateMapping } from './mapping.js';
import { performDiffAnalysis, performFullUpload, applyDiffChanges } from './diff/run.js';
import { updateAllPreviews } from './preview.js';

/**
 * Open the import modal for a given collection. Resets all wizard
 * state and the Excel dropzone, then activates the paste tab.
 *
 * @param {string} name - collection name
 */
export function openImport(name) {
    state.activeCollection = name;
    if (els.importTarget) els.importTarget.value = name;

    resetImportState();
    if (els.pasteArea) els.pasteArea.value = '';
    if (els.codeSeparator) els.codeSeparator.value = '.';
    if (els.descSeparator) els.descSeparator.value = ' ';

    resetExcelUploadUI();

    // Default to the paste tab.
    document.querySelectorAll('.source-tab').forEach((t) => t.classList.remove('active'));
    const pasteTab = document.querySelector('.source-tab[data-source="paste"]');
    if (pasteTab) pasteTab.classList.add('active');

    document.querySelectorAll('.import-source-content').forEach((c) => c.classList.remove('active'));
    const pasteContent = document.getElementById('importSourcePaste');
    if (pasteContent) pasteContent.classList.add('active');

    showImportStep('paste');
    openModal('import');
}

/**
 * Install all the wizard event listeners. Called once at bootstrap.
 */
export function initImportWizard() {
    // Paste handling.
    els.pasteArea?.addEventListener('paste', (e) => {
        setTimeout(() => {
            const text = els.pasteArea.value.trim();
            if (text) processPastedData(text);
        }, 100);
    });

    // "Next" (step 1 → 2)
    els.importBtns.next?.addEventListener('click', () => {
        const text = els.pasteArea.value.trim();
        if (!text) return alert('Сначала вставьте данные.');
        processPastedData(text);
    });

    // "Back" — step 3 → 2 → 1
    els.importBtns.back?.addEventListener('click', () => {
        if (els.importSteps.diff?.classList.contains('active')) {
            showImportStep('mapping');
        } else if (els.importSteps.mapping?.classList.contains('active')) {
            showImportStep('paste');
        }
    });

    // "Compare with DB" (step 2 → diff)
    els.importBtns.compare?.addEventListener('click', async () => {
        if (!validateMapping()) return;
        await performDiffAnalysis();
    });

    // "Upload everything" (full overwrite)
    els.importBtns.upload?.addEventListener('click', async () => {
        if (!validateMapping()) return;
        await performFullUpload();
    });

    // "Apply changes" (diff apply)
    els.importBtns.apply?.addEventListener('click', async () => {
        await applyDiffChanges();
    });

    // Separator inputs.
    els.codeSeparator?.addEventListener('input', () => {
        importData.codeSeparator = els.codeSeparator.value || '.';
        updateAllPreviews();
    });
    els.descSeparator?.addEventListener('input', () => {
        importData.descSeparator = els.descSeparator.value || ' ';
        updateAllPreviews();
    });

    initImportSourceTabs();
    initExcelUpload();
    initDiffTabs();
}

/**
 * Switch the wizard step. Also rearranges the action buttons to match
 * the current step (only the ones that make sense are visible).
 *
 * @param {'paste'|'mapping'|'diff'|'progress'} stepName
 */
export function showImportStep(stepName) {
    Object.values(els.importSteps).forEach((s) => {
        if (s) s.classList.remove('active');
    });
    if (els.importSteps[stepName]) {
        els.importSteps[stepName].classList.add('active');
    }

    const btns = els.importBtns;
    btns.back?.classList.add('hidden');
    btns.next?.classList.add('hidden');
    btns.compare?.classList.add('hidden');
    btns.upload?.classList.add('hidden');
    btns.apply?.classList.add('hidden');

    switch (stepName) {
        case 'paste':
            btns.next?.classList.remove('hidden');
            break;
        case 'mapping':
            btns.back?.classList.remove('hidden');
            btns.compare?.classList.remove('hidden');
            btns.upload?.classList.remove('hidden');
            break;
        case 'diff':
            btns.back?.classList.remove('hidden');
            btns.apply?.classList.remove('hidden');
            break;
        case 'progress':
            // No buttons during the import.
            break;
    }
}
