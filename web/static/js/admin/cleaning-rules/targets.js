/**
 * Cleaning-rules target field metadata and DOM helpers.
 *
 * The "apply to" multiselect uses Fa icons + labels keyed by a
 * canonical target id (description / hierarchy / hierarchy_level / *).
 * The pills themselves are <label> elements wrapping a hidden
 * <input type="checkbox">; clicking the pill toggles the checkbox.
 *
 * Split out of the original module.js (353 LoC) for module size
 * management.
 */

export const TARGET_LABELS = Object.freeze({
    description: 'Описание',
    hierarchy: 'Иерархия',
    hierarchy_level: 'Уровни иерархии',
    '*': 'Все поля',
});

export const TARGET_ICONS = Object.freeze({
    description: 'fa-align-left',
    hierarchy: 'fa-sitemap',
    hierarchy_level: 'fa-layer-group',
    '*': 'fa-globe',
});

/**
 * Hide the add-rule form (used by cancel button and on successful add).
 */
export function closeAddForm() {
    const form = document.getElementById('addRuleForm');
    const section = document.getElementById('addRuleSection');
    if (form) form.hidden = true;
    if (section) section.classList.remove('open');
}

/**
 * Sync the `.target-pill.checked` class with the underlying checkbox
 * state. Called after every checkbox toggle (manual or programmatic).
 */
export function syncPillChecked() {
    document.querySelectorAll('.target-pill').forEach((pill) => {
        const cb = pill.querySelector('input[type="checkbox"]');
        pill.classList.toggle('checked', !!(cb && cb.checked));
    });
}
