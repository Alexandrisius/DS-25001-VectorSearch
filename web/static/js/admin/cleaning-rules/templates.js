/**
 * Built-in cleaning rule templates.
 *
 * Clicking a chip in the UI inserts these values into the add-rule form.
 * Order matters — the first match in the list is rendered first.
 *
 * Also owns `renderTemplates()` which paints the chip list into the
 * `templatesList` container (originally on CleaningRulesModule; moved
 * here during the K2 module split).
 */
import { escapeHtml } from '../../shared/dom.js';

export const BUILTIN_TEMPLATES = Object.freeze([
    {
        id: 'remove-section-prefix',
        name: 'Удалить «Раздел N.N» / «Группа N.N»',
        pattern: '^(Раздел|Группа)\\s+[\\d\\.\\s]+',
        replacement: '',
        description: 'Убирает префиксы «Раздел 1.2.3» / «Группа 4.5» в начале строк иерархии.',
        apply_to_columns: ['hierarchy', 'hierarchy_level'],
    },
    {
        id: 'collapse-whitespace',
        name: 'Схлопнуть лишние пробелы',
        pattern: '\\s+',
        replacement: ' ',
        description: 'Заменяет любые последовательности пробелов и переносов одним пробелом.',
        apply_to_columns: ['*'],
    },
    {
        id: 'trim-quotes',
        name: 'Убрать обрамляющие кавычки',
        pattern: '^["«»\'`]+|["«»\'`]+$',
        replacement: '',
        description: 'Снимает " « » ‘ ’ ` в начале и конце строки.',
        apply_to_columns: ['description', 'hierarchy', 'hierarchy_level'],
    },
    {
        id: 'remove-parentheses',
        name: 'Удалить текст в скобках',
        pattern: '\\s*\\([^)]*\\)',
        replacement: '',
        description: 'Удаляет «(любой текст)» вместе с обрамляющими пробелами.',
        apply_to_columns: ['description', 'hierarchy', 'hierarchy_level'],
    },
    {
        id: 'remove-trademark-prefix',
        name: 'Убрать «Товарный знак:»',
        pattern: '^Товарный\\s+знак[:\\s]*',
        replacement: '',
        description: 'Удаляет префикс «Товарный знак:» в начале описания.',
        apply_to_columns: ['description'],
    },
    {
        id: 'remove-special-chars',
        name: 'Удалить спецсимволы',
        pattern: '[^\\w\\s\\-./()№]',
        replacement: '',
        description: 'Оставляет только буквы, цифры, пробелы, тире, точки, скобки, №.',
        apply_to_columns: ['description', 'hierarchy', 'hierarchy_level'],
    },
    {
        id: 'remove-trailing-dot',
        name: 'Убрать точку в конце',
        pattern: '\\.+$',
        replacement: '',
        description: 'Удаляет финальные точки в конце строки.',
        apply_to_columns: ['description', 'hierarchy', 'hierarchy_level'],
    },
]);

/**
 * Render the template chips into the `templatesList` container. Each
 * chip gets a `data-template-id` so the events module can wire it
 * to `applyTemplate()`.
 */
export function renderTemplates() {
    const list = document.getElementById('templatesList');
    if (!list) return;
    list.innerHTML = BUILTIN_TEMPLATES.map((t) => `
        <button class="template-chip" type="button"
                data-template-id="${escapeHtml(t.id)}"
                title="${escapeHtml(t.description)}">
            <i class="fas fa-magic" aria-hidden="true"></i>
            ${escapeHtml(t.name)}
        </button>
    `).join('');
    /* Click handlers are bound in events.js via delegation. */
}
