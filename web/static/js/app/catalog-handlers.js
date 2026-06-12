/**
 * Click handlers for the catalog sidebar (db cards, result paths).
 *
 * The `db-card` is a quick-select for a database (mirrors clicking
 * the option in the custom dropdown). The `result-category-path` is
 * a clickable breadcrumb inside a search-result row that opens the
 * catalog at that category.
 *
 * Split out of app/main.js (115 LoC) for module size management.
 */

import { els } from './els.js';
import { setCurrentDatabase } from './database.js';
import { navigateToCategoryInCatalog } from './catalog/navigation.js';

/**
 * Install the delegated handler. Idempotent.
 */
let installed = false;
export function initCatalogHandlers() {
    if (installed) return;
    installed = true;

    document.addEventListener('click', (e) => {
        // Database card click → select database
        const dbCard = e.target.closest('.db-card');
        if (dbCard) {
            const dbName = dbCard.dataset.name;
            const option = els.customOptionsContainer
                ? Array.from(els.customOptionsContainer.children).find((div) => div.dataset.value === dbName)
                : null;
            if (option) option.click();
            return;
        }

        // Result category path → navigate in catalog
        const catPath = e.target.closest('.result-category-path');
        if (catPath) {
            const categoryPath = catPath.dataset.categoryPath;
            if (categoryPath) {
                navigateToCategoryInCatalog(categoryPath);
            }
        }
    });
}
