/**
 * Diff analysis flow.
 *
 *   1. If we have a cacheKey, fetch the full Excel data.
 *   2. Make sure cleaning rules are loaded (they're applied inside
 *      buildRecordsFromMapping).
 *   3. Fetch existing records from the collection.
 *   4. Derive existing folders from the existing records' path_level_N
 *      fields (mirrors the new-records extraction).
 *   5. Run analyzeChanges + analyzeFolderChanges.
 *   6. Render the diff UI.
 *
 * Split out of the original run.js for module size management.
 */

import { state } from '../../state.js';
import { els } from '../../els.js';
import { importData, diffData } from '../state.js';
import { buildRecordsFromMapping } from '../mapping.js';
import { analyzeChanges, analyzeFolderChanges, extractFoldersFromRecords } from './analyze.js';
import { updateDiffUI } from './render.js';
import { loadFullExcelData } from './load.js';
import { CleaningRulesModule } from '../../cleaning-rules/list.js';
import { showImportStep } from '../wizard.js';

export async function performDiffAnalysis() {
    if (importData.cacheKey) {
        const loaded = await loadFullExcelData();
        if (!loaded) return;
    }

    showImportStep('diff');
    els.diffLoading?.classList.remove('hidden');
    if (els.diffTableBody) els.diffTableBody.innerHTML = '';
    els.diffEmpty?.classList.add('hidden');

    try {
        console.log(`📥 Загрузка текующих записей из коллекции '${state.activeCollection}'...`);

        if (!state.cleaningRules || state.cleaningRules.length === 0) {
            console.log('⚠️ Правила очистки не загружены, загружаем...');
            await CleaningRulesModule.load();
        }

        const res = await fetch(`/get_all_codes?database=${state.activeCollection}`);
        if (!res.ok) {
            throw new Error('Не удалось загрузить текущие записи');
        }

        const data = await res.json();
        diffData.existingRecords = data.records || {};
        console.log(`✅ Загружено ${Object.keys(diffData.existingRecords).length} записей из базы`);

        console.log(`📁 Извлечение папок из существующих материалов...`);

        const existingRecordsArray = Object.values(diffData.existingRecords).map((record) => {
            let hierarchy = '';
            if (record.path_depth && record.path_depth > 0) {
                const parts = [];
                for (let i = 1; i <= record.path_depth; i++) {
                    const part = record[`path_level_${i}`];
                    if (part) parts.push(part);
                }
                hierarchy = parts.join(' → ');
            }
            return {
                code: record.code,
                description: record.full_description || record.description,
                hierarchy,
            };
        });

        diffData.existingFolders = extractFoldersFromRecords(existingRecordsArray);

        const newRecords = buildRecordsFromMapping();

        const materialDiff = analyzeChanges(newRecords, diffData.existingRecords);
        diffData.added = materialDiff.added;
        diffData.modified = materialDiff.modified;
        diffData.deleted = materialDiff.deleted;
        diffData.unchanged = materialDiff.unchanged;

        const folderDiff = analyzeFolderChanges(newRecords, diffData.existingFolders);
        diffData.folderChanges = folderDiff;

        console.log(`📊 Анализ: +${materialDiff.added.length} добавлено, ~${materialDiff.modified.length} изменено, -${materialDiff.deleted.length} удалено | Папки: +${folderDiff.added.length} новых`);

        updateDiffUI();
    } catch (e) {
        console.error('❌ Ошибка diff-анализа:', e);
        alert('Ошибка загрузки данных из базы: ' + e.message);
        showImportStep('mapping');
    } finally {
        els.diffLoading?.classList.add('hidden');
    }
}
