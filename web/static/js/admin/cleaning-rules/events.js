/**
 * Wiring for the cleaning-rules UI on the settings page.
 *
 * After the K2 split, the four concerns live in separate modules:
 *   - list.js      → load/save/add/delete/toggle + render
 *   - form.js      → collectDraft/clearForm/applyTemplate
 *   - preview.js   → openPreviewModalById/ForDraft
 *   - targets.js   → closeAddForm/syncPillChecked (DOM helpers)
 *
 * - Toggle visibility of the add-form and the templates section
 * - Delegated click handler for rule actions (toggle, preview, delete)
 *   so we don't have inline `onclick="CleaningRulesModule.X(...)"` attributes
 *   in dynamically-rendered HTML.
 * - Delegated click for the target pills (which toggle the hidden
 *   checkboxes inside them).
 */

import { CleaningRulesModule } from './list.js';
import { CleaningRulesModule_form } from './form.js';
import { CleaningRulesModule_preview } from './preview.js';
import { closeAddForm, syncPillChecked } from './targets.js';

export function initCleaningRulesEvents() {
    // --- Add-form toggle ---
    const addToggle = document.getElementById('addRuleToggle');
    const addForm = document.getElementById('addRuleForm');
    const addSection = document.getElementById('addRuleSection');
    addToggle?.addEventListener('click', () => {
        if (!addForm) return;
        const willShow = addForm.hidden;
        addForm.hidden = !willShow;
        addSection?.classList.toggle('open', willShow);
        if (willShow) {
            document.getElementById('newRuleName')?.focus();
        }
    });

    // --- Add-form buttons ---
    document.getElementById('cancelAddRuleBtn')?.addEventListener('click', () => {
        closeAddForm();
        CleaningRulesModule_form.clearForm();
    });

    document.getElementById('addCleaningRuleBtn')?.addEventListener('click', () => {
        const result = CleaningRulesModule_form.collectDraft();
        if (!result.valid) {
            alert(result.errors.join('\n'));
            return;
        }
        CleaningRulesModule.add(result.draft);
        CleaningRulesModule_form.clearForm();
    });

    document.getElementById('saveCleaningRulesBtn')?.addEventListener('click', () => {
        CleaningRulesModule.save();
    });

    document.getElementById('previewCleaningRuleBtn')?.addEventListener('click', () => {
        const result = CleaningRulesModule_form.collectDraft();
        if (!result.valid) {
            alert(result.errors.join('\n'));
            return;
        }
        CleaningRulesModule_preview.openPreviewModalForDraft(result.draft);
    });

    // --- Templates toggle ---
    document.getElementById('templatesToggle')?.addEventListener('click', () => {
        const list = document.getElementById('templatesList');
        const section = document.getElementById('templatesSection');
        if (!list || !section) return;
        const willShow = list.hidden;
        list.hidden = !willShow;
        section.classList.toggle('open', willShow);
    });

    // --- Pill click → toggle hidden checkbox ---
    document.querySelectorAll('.target-pill').forEach((pill) => {
        pill.addEventListener('click', (e) => {
            if (e.target.tagName === 'INPUT') return;
            const cb = pill.querySelector('input[type="checkbox"]');
            if (!cb) return;
            cb.checked = !cb.checked;
            pill.classList.toggle('checked', cb.checked);
        });
    });

    // --- Delegated handler for rule actions ---
    const list = document.getElementById('cleaningRulesList');
    list?.addEventListener('click', (e) => {
        const target = e.target.closest('[data-action]');
        if (!target) return;
        const action = target.dataset.action;
        const ruleId = target.dataset.ruleId;
        if (!ruleId) return;
        if (action === 'toggle-rule') {
            CleaningRulesModule.toggle(ruleId);
        } else if (action === 'preview-rule') {
            CleaningRulesModule_preview.openPreviewModalById(ruleId);
        } else if (action === 'delete-rule') {
            CleaningRulesModule.delete(ruleId);
        }
    });

    // --- Preview modal close ---
    document.querySelectorAll('[data-close="preview"]').forEach((btn) => {
        btn.addEventListener('click', () => {
            document.getElementById('cleaningRulePreviewModal')?.classList.remove('active');
        });
    });
}

// Keep `syncPillChecked` exported for code that imports it from here.
export { syncPillChecked };
