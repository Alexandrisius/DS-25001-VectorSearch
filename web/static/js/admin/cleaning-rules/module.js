/**
 * Cleaning-rules module.
 *
 * Owns the list of regex-based cleaning rules and the lifecycle of the
 * settings-page UI (load, save, add, delete, toggle, render, preview).
 *
 * The original implementation was a plain object with `this`-bound
 * methods. We keep that pattern for compatibility and to minimise the
 * diff — the module is exported as a single `CleaningRulesModule`
 * namespace so callers can use `CleaningRulesModule.load()` etc.
 *
 * IMPORTANT: methods must be called as `module.method(...)`, never
 * unbound (`var f = module.method; f();`). Inline event handlers in
 * templates rely on `this` referring to the module.
 */

import { state } from '../state.js';
import { authFetch } from '../../shared/api.js';
import { escapeHtml } from '../../shared/dom.js';
import { BUILTIN_TEMPLATES } from './templates.js';

const TARGET_LABELS = Object.freeze({
    description: 'Описание',
    hierarchy: 'Иерархия',
    hierarchy_level: 'Уровни иерархии',
    '*': 'Все поля',
});

const TARGET_ICONS = Object.freeze({
    description: 'fa-align-left',
    hierarchy: 'fa-sitemap',
    hierarchy_level: 'fa-layer-group',
    '*': 'fa-globe',
});

/**
 * @param {{id: string|null, name: string, pattern: string, replacement: string, enabled: boolean, apply_to_columns: string[]}} r
 * @returns {Object}
 */
function serializeForApi(r) {
    return {
        id: r.id || null,
        name: r.name,
        pattern: r.pattern,
        replacement: r.replacement || '',
        enabled: r.enabled,
        apply_to_columns: r.apply_to_columns,
        sort_order: r.sort_order || 0,
    };
}

function applyRuleToText(rule, text) {
    if (!text) return '';
    try {
        const re = new RegExp(rule.pattern, 'g');
        return text.replace(re, rule.replacement || '');
    } catch {
        return text;
    }
}

function closeAddForm() {
    const form = document.getElementById('addRuleForm');
    const section = document.getElementById('addRuleSection');
    if (form) form.hidden = true;
    if (section) section.classList.remove('open');
}

function syncPillChecked() {
    document.querySelectorAll('.target-pill').forEach((pill) => {
        const cb = pill.querySelector('input[type="checkbox"]');
        pill.classList.toggle('checked', !!(cb && cb.checked));
    });
}

export const CleaningRulesModule = {
    TARGET_LABELS,
    TARGET_ICONS,

    async load() {
        try {
            const res = await authFetch('/admin/cleaning_rules');
            if (res.ok) {
                const data = await res.json();
                state.cleaningRules = data.rules || [];
                console.log(`🧹 Загружено ${state.cleaningRules.length} правил очистки`);
                this.render();
                this.renderTemplates();
            } else {
                console.error(`❌ Ошибка загрузки правил: ${res.status}`);
            }
        } catch (e) {
            console.error('❌ Исключение при загрузке правил очистки:', e);
        }
    },

    async save() {
        try {
            const payload = state.cleaningRules.map((r) => serializeForApi(r));
            const response = await authFetch('/admin/cleaning_rules', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (response.ok) {
                const data = await response.json();
                state.cleaningRules = data.rules || [];
                this.render();
                alert('Правила очистки сохранены');
            } else {
                const err = await response.json().catch(() => ({ detail: 'Ошибка' }));
                alert(`Ошибка: ${err.detail}`);
            }
        } catch (e) {
            console.error('Ошибка сохранения правил:', e);
            alert('Ошибка сохранения');
        }
    },

    add(draft) {
        state.cleaningRules.push({
            id: null,
            name: draft.name,
            pattern: draft.pattern,
            replacement: draft.replacement || '',
            enabled: true,
            apply_to_columns: draft.apply_to_columns,
        });
        this.render();
        closeAddForm();
    },

    delete(ruleId) {
        if (!confirm('Удалить это правило очистки?')) return;
        state.cleaningRules = state.cleaningRules.filter((r) => r.id !== ruleId);
        this.render();
    },

    toggle(ruleId) {
        const rule = state.cleaningRules.find((r) => r.id === ruleId);
        if (rule) {
            rule.enabled = !rule.enabled;
            this.render();
        }
    },

    /**
     * Read the current values of the add-rule form and validate them.
     *
     * @returns {{valid: boolean, errors: string[], draft: {name: string, pattern: string, replacement: string, apply_to_columns: string[]}}}
     */
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
        // Reset to the default — only «Уровни иерархии».
        document.querySelectorAll('input[name="newRuleTarget"]').forEach((cb) => {
            cb.checked = cb.value === 'hierarchy_level';
        });
    },

    render() {
        const container = document.getElementById('cleaningRulesList');
        if (!container) return;

        if (!state.cleaningRules || state.cleaningRules.length === 0) {
            container.innerHTML = `
                <p style="color: var(--adm-text-sec); text-align: center; padding: 20px; margin: 0;">
                    Нет правил. Добавьте первое — или используйте готовый шаблон выше.
                </p>`;
            return;
        }

        container.innerHTML = state.cleaningRules.map((rule) => {
            const targets = rule.apply_to_columns && rule.apply_to_columns.length > 0
                ? rule.apply_to_columns
                : ['*'];
            const badges = targets.map((t) => `
                <span class="rule-target-badge">
                    <i class="fas ${TARGET_ICONS[t] || 'fa-tag'}"></i>
                    ${escapeHtml(TARGET_LABELS[t] || t)}
                </span>
            `).join('');
            const pattern = escapeHtml(rule.pattern);
            const replacement = escapeHtml(rule.replacement || '');
            // Use data-action attributes + delegated handler (no inline onclick).
            return `
                <div class="cleaning-rule-item ${rule.enabled ? '' : 'disabled'}" data-rule-id="${escapeHtml(rule.id)}">
                    <div class="rule-toggle">
                        <label class="toggle-switch">
                            <input type="checkbox" ${rule.enabled ? 'checked' : ''}
                                   data-action="toggle-rule" data-rule-id="${escapeHtml(rule.id)}">
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="rule-body">
                        <div class="rule-line-1">
                            <span class="rule-name">${escapeHtml(rule.name)}</span>
                            <code class="rule-pattern">/${pattern}/${replacement}/</code>
                        </div>
                        <div class="rule-line-2">${badges}</div>
                    </div>
                    <div class="rule-actions">
                        <button class="btn-icon" data-action="preview-rule" data-rule-id="${escapeHtml(rule.id)}" title="Тест">
                            <i class="fas fa-vial"></i>
                        </button>
                        <button class="btn-icon danger" data-action="delete-rule" data-rule-id="${escapeHtml(rule.id)}" title="Удалить">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    },

    renderTemplates() {
        const list = document.getElementById('templatesList');
        if (!list) return;
        list.innerHTML = BUILTIN_TEMPLATES.map((t) => `
            <button class="template-chip" type="button"
                    data-template-id="${escapeHtml(t.id)}"
                    title="${escapeHtml(t.description)}">
                <i class="fas fa-magic"></i>
                ${escapeHtml(t.name)}
            </button>
        `).join('');
        list.querySelectorAll('.template-chip').forEach((chip) => {
            chip.addEventListener('click', () => this.applyTemplate(chip.dataset.templateId));
        });
    },

    applyTemplate(templateId) {
        const tpl = BUILTIN_TEMPLATES.find((t) => t.id === templateId);
        if (!tpl) return;
        // Раскрыть форму, если свёрнута
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
            '<em style="color: var(--adm-text-sec);">Нажмите «Запустить»...</em>';
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

    _applyRuleToText: applyRuleToText,
    _serializeForApi: serializeForApi,
    _closeAddForm: closeAddForm,
    _syncPillChecked: syncPillChecked,
};
