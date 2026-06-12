/**
 * Cleaning-rules list: load from server, render, delete, toggle.
 *
 * Owns state.cleaningRules and the rendered UI list. The CRUD-like
 * operations stay on this object (a single namespace) for backwards
 * compatibility with the rest of the codebase.
 *
 * Split out of the original module.js (353 LoC) for module size
 * management.
 */

import { state } from '../state.js';
import { authFetch } from '../../shared/api.js';
import { escapeHtml } from '../../shared/dom.js';
import { TARGET_LABELS, TARGET_ICONS } from './targets.js';
import { closeAddForm } from './targets.js';
import { renderTemplates } from './templates.js';

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
                renderTemplates();
            } else {
                console.error(`❌ Ошибка загрузки правил: ${res.status}`);
            }
        } catch (e) {
            console.error('❌ Исключение при загрузке правил очистки:', e);
        }
    },

    async save() {
        try {
            const payload = state.cleaningRules.map((r) => ({
                id: r.id || null,
                name: r.name,
                pattern: r.pattern,
                replacement: r.replacement || '',
                enabled: r.enabled,
                apply_to_columns: r.apply_to_columns,
                sort_order: r.sort_order || 0,
            }));
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

    render() {
        const container = document.getElementById('cleaningRulesList');
        if (!container) return;

        if (!state.cleaningRules || state.cleaningRules.length === 0) {
            container.innerHTML = `
                <p class="cleaning-rules-list__empty">Нет правил. Добавьте первое — или используйте готовый шаблон выше.</p>`;
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
                            <i class="fas fa-vial" aria-hidden="true"></i>
                        </button>
                        <button class="btn-icon danger" data-action="delete-rule" data-rule-id="${escapeHtml(rule.id)}" title="Удалить">
                            <i class="fas fa-trash" aria-hidden="true"></i>
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    },
};
