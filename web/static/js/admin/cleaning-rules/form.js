/**
 * Cleaning-rules add form: open/close, draft collection, validation,
 * applying templates.
 *
 * The form lives in admin.html as a hidden <div id="addRuleForm">.
 * The toggle button shows/hides it. submit pulls the form values,
 * validates the regex, and either adds the rule to the list or
 * surfaces a combined error message.
 *
 * Templates are pre-built rule snippets (see templates.js); clicking
 * a template chip pre-fills the form.
 *
 * Split out of the original module.js (353 LoC) for module size
 * management.
 */

import { BUILTIN_TEMPLATES } from './templates.js';
import { syncPillChecked } from './targets.js';

export const CleaningRulesModule_form = {
    collectDraft() {
        const name = document.getElementById('newRuleName').value.trim();
        const pattern = document.getElementById('newRulePattern').value.trim();
        const replacement = document.getElementById('newRuleReplacement').value;
        const targets = Array.from(
            document.querySelectorAll('input[name="newRuleTarget"]:checked'),
        ).map((cb) => cb.value);

        const errors = [];
        if (!name) errors.push('Введите название');
        if (!pattern) errors.push('Введите regex-паттерн');
        if (targets.length === 0) errors.push('Выберите хотя бы одно поле');
        try {
            new RegExp(pattern);
        } catch (e) {
            errors.push(`Невалидный regex: ${e.message}`);
        }

        return {
            valid: errors.length === 0,
            errors,
            draft: { name, pattern, replacement, apply_to_columns: targets },
        };
    },

    clearForm() {
        document.getElementById('newRuleName').value = '';
        document.getElementById('newRulePattern').value = '';
        document.getElementById('newRuleReplacement').value = '';
        document.querySelectorAll('input[name="newRuleTarget"]').forEach((cb) => {
            cb.checked = cb.value === 'hierarchy_level';
        });
    },

    applyTemplate(templateId) {
        const tpl = BUILTIN_TEMPLATES.find((t) => t.id === templateId);
        if (!tpl) return;
        const form = document.getElementById('addRuleForm');
        const section = document.getElementById('addRuleSection');
        if (form && form.hidden) {
            form.hidden = false;
            section?.classList.add('open');
        }
        syncPillChecked();
        document.getElementById('newRuleName').value = tpl.name;
        document.getElementById('newRulePattern').value = tpl.pattern;
        document.getElementById('newRuleReplacement').value = tpl.replacement || '';
        document.querySelectorAll('input[name="newRuleTarget"]').forEach((cb) => {
            cb.checked = tpl.apply_to_columns.includes(cb.value)
                || tpl.apply_to_columns.includes('*');
        });
        syncPillChecked();
        document.getElementById('newRuleName').focus();
        document.getElementById('addRuleToggle')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    },
};
