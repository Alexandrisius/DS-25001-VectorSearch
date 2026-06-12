/**
 * Apply cleaning rules to a single string.
 *
 * Used by the import wizard to sanitise description / hierarchy values
 * before they are sent to the server. The rules themselves are stored
 * on the global admin `state.cleaningRules` array.
 *
 * @param {string|null|undefined} text
 * @param {string|null} [target=null] - 'description' | 'hierarchy' | 'hierarchy_level' | null
 * @returns {string}
 */
import { state } from '../state.js';

export function applyCleaningRules(text, target = null) {
    if (!text || typeof text !== 'string') return text;

    const rules = state.cleaningRules;
    if (!rules || rules.length === 0) return text.trim();

    let result = text;
    for (const rule of rules) {
        if (!rule.enabled) continue;
        const applyTo = rule.apply_to_columns || ['*'];
        const isApplicable =
            applyTo.includes('*') || (target && applyTo.includes(target));
        if (!isApplicable) continue;

        try {
            const regex = new RegExp(rule.pattern, 'g');
            result = result.replace(regex, rule.replacement || '');
        } catch (e) {
            console.warn(`❌ Invalid regex in rule '${rule.name}':`, e);
        }
    }
    return result.trim();
}
