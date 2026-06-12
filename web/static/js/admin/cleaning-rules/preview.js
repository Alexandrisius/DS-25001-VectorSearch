/**
 * Cleaning-rule preview modal.
 *
 * Renders the "before → after" trace for a rule's regex against a
 * user-supplied test string. Reached two ways:
 *   1. From the saved-rule list (via openPreviewModalById → reads
 *      the rule from state.cleaningRules).
 *   2. From the "Test" button on the add-rule form (via
 *      openPreviewModalForDraft → uses the in-progress draft).
 *
 * Split out of the original module.js (353 LoC) for module size
 * management.
 */

import { state } from '../state.js';
import { escapeHtml } from '../../shared/dom.js';
import { TARGET_LABELS, TARGET_ICONS } from './targets.js';

export const CleaningRulesModule_preview = {
    openPreviewModalById(ruleId) {
        const rule = state.cleaningRules.find((r) => r.id === ruleId);
        if (!rule) return;
        this._openPreviewModal(rule);
    },

    openPreviewModalForDraft(draft) {
        const rule = {
            id: null,
            name: draft.name,
            pattern: draft.pattern,
            replacement: draft.replacement,
            enabled: true,
            apply_to_columns: draft.apply_to_columns,
        };
        this._openPreviewModal(rule);
    },

    _openPreviewModal(rule) {
        const modal = document.getElementById('cleaningRulePreviewModal');
        const meta = document.getElementById('previewMeta');
        if (!modal || !meta) return;

        const targets = (rule.apply_to_columns && rule.apply_to_columns.length > 0)
            ? rule.apply_to_columns
            : ['*'];
        meta.innerHTML = `
            <div class="preview-rule-name">${escapeHtml(rule.name)}</div>
            <code class="preview-rule-pattern">/${escapeHtml(rule.pattern)}/${escapeHtml(rule.replacement || '')}/</code>
            <div class="preview-rule-targets">
                ${targets.map((t) => `
                    <span class="rule-target-badge">
                        <i class="fas ${TARGET_ICONS[t] || 'fa-tag'}"></i>
                        ${escapeHtml(TARGET_LABELS[t] || t)}
                    </span>
                `).join('')}
            </div>
        `;
        document.getElementById('previewTestInput').value = '';
        document.getElementById('previewOutput').innerHTML =
            '<em class="preview-output__placeholder">Нажмите «Запустить»...</em>';
        document.getElementById('previewSteps').innerHTML = '';
        modal.classList.add('active');

        const runBtn = document.getElementById('runPreviewBtn');
        runBtn.onclick = () => {
            const input = document.getElementById('previewTestInput').value;
            const result = applyRuleToText(rule, input);
            const out = document.getElementById('previewOutput');
            out.textContent = result || '(пусто)';

            let matched = false;
            try { matched = new RegExp(rule.pattern, 'g').test(input); } catch { matched = false; }

            document.getElementById('previewSteps').innerHTML = `
                <div class="preview-step">
                    <span class="step-label">Шаг 1</span>
                    <code>${escapeHtml(input) || '(пусто)'}</code>
                    <span class="arrow">→</span>
                    <code>${escapeHtml(result) || '(пусто)'}</code>
                    <span class="step-status ${matched ? 'matched' : 'no-match'}">
                        <i class="fas ${matched ? 'fa-check' : 'fa-minus'}"></i>
                        ${matched ? 'найдено' : 'без совпадений'}
                    </span>
                </div>
            `;
        };
    },
};

/**
 * Apply a single rule to a string. Used by the preview "Run" button.
 * Returns the original text if the regex is invalid.
 */
export function applyRuleToText(rule, text) {
    if (!text) return '';
    try {
        const re = new RegExp(rule.pattern, 'g');
        return text.replace(re, rule.replacement || '');
    } catch {
        return text;
    }
}
