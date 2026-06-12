/**
 * Diff & apply flow.
 *
 *   - performDiffAnalysis:  buildRecords → fetch existing → diff → render
 *   - performFullUpload:    "Upload everything" button (overwrite)
 *   - applyDiffChanges:      "Apply changes" button (incremental)
 *   - uploadExcelFileToServer: helper for performFullUpload
 *
 * The three flows are kept in one file because they share state and
 * call into the same helpers (buildRecordsFromMapping, getOrderedSelection,
 * watchJob / pollJobUntilComplete).
 */

import { state } from '../../state.js';
import { els } from '../../els.js';
import { authFetch } from '../../../shared/api.js';
import { diffData, importData } from '../state.js';
import { buildRecordsFromMapping, getOrderedSelection } from '../mapping.js';
import { analyzeChanges, analyzeFolderChanges, extractFoldersFromRecords } from './analyze.js';
import { updateDiffUI } from './render.js';
import { loadFullExcelData } from './load.js';
import { CleaningRulesModule } from '../../cleaning-rules/module.js';
import { showImportStep } from '../wizard.js';
import { closeModal } from '../../modals.js';
import { loadCollections } from '../../collections/list.js';
import { watchJob, pollJob, pollJobUntilComplete } from '../jobs.js';

/**
 * Step-by-step:
 *   1. If we have a cacheKey, fetch the full Excel data.
 *   2. Make sure cleaning rules are loaded (they're applied inside
 *      buildRecordsFromMapping).
 *   3. Fetch existing records from the collection.
 *   4. Derive existing folders from the existing records' path_level_N
 *      fields (mirrors the new-records extraction).
 *   5. Run analyzeChanges + analyzeFolderChanges.
 *   6. Render the diff UI.
 */
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
        console.log(`📥 Загрузка текущих записей из коллекции '${state.activeCollection}'...`);

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

        // Derive existing folders from materials (not from a separate
        // /get_all_folders call — see diff/analyze.js for why).
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

/**
 * "Upload everything" — full overwrite of the collection.
 *
 * For Excel uploads we already have a cache_key, so we send that
 * instead of the in-memory records (which would be 28 MB for 142k
 * rows). For paste-source imports we build the records here.
 */
export async function performFullUpload() {
    let cacheKey = importData.cacheKey;

    if (importData.excelFile && !cacheKey) {
        const loaded = await uploadExcelFileToServer();
        if (!loaded) return;
        cacheKey = loaded;
    }

    if (!cacheKey) {
        // No Excel — fall back to records in memory.
        const records = buildRecordsFromMapping();
        if (records.length === 0) {
            alert('Нет записей для загрузки. Сначала загрузите Excel.');
            return;
        }
        const hierarchyCols = getOrderedSelection('hierarchy');
        const payload = {
            collection_name: state.activeCollection,
            records: records.map((r) => ({
                code: r.code,
                description: r.description,
                hierarchy: hierarchyCols.length > 0 ? r.hierarchy : undefined,
                meta: r.meta,
            })),
            recreate: false,
        };
        showImportStep('progress');
        els.importStatusText.innerText = 'Отправка задачи...';
        try {
            const res = await authFetch('/admin/import', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            const json = await res.json();
            pollJob(json.job_id);
        } catch (e) {
            if (e.message !== 'Unauthorized') {
                els.importStatusText.innerText = 'Ошибка отправки';
                alert('Ошибка импорта: ' + e.message);
            }
        }
        return;
    }

    // Excel cache_key path
    const codeCols = getOrderedSelection('code');
    const descCols = getOrderedSelection('desc');
    const hierarchyCols = getOrderedSelection('hierarchy');

    if (codeCols.length === 0 || descCols.length === 0) {
        alert('Не выбраны колонки для кода или описания.\n\nОткройте маппинг колонок в шаге 2.');
        return;
    }

    const columnMapping = {
        code: codeCols,
        description: descCols,
        hierarchy: hierarchyCols,
        code_separator: importData.codeSeparator || '.',
        description_separator: importData.descSeparator || ' ',
    };
    console.log('[performFullUpload] columnMapping:', columnMapping);

    const payload = {
        collection_name: state.activeCollection,
        cache_key: cacheKey,
        column_mapping: columnMapping,
        recreate: false,
    };

    showImportStep('progress');
    els.importStatusText.innerText = 'Отправка задачи (через cache_key)...';

    try {
        const res = await authFetch('/admin/import', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        const json = await res.json();
        watchJob(json.job_id);
    } catch (e) {
        if (e.message !== 'Unauthorized') {
            els.importStatusText.innerText = 'Ошибка отправки';
            alert('Ошибка импорта: ' + e.message);
        }
    }
}

/**
 * Helper — upload the in-memory Excel file to the server and return
 * the cache_key. The file is on `importData.excelFile`.
 *
 * NOTE: Original code referenced `state.importData.sourceFile` which
 * never exists in the code path. The early return at the top of this
 * function (which checks `importData.excelFile`) meant the typo was
 * unreachable. We keep the early return behaviour.
 */
export async function uploadExcelFileToServer() {
    if (!importData.excelFile) return null;

    const fd = new FormData();
    fd.append('file', importData.excelFile);
    els.importStatusText.innerText = 'Загрузка файла на сервер...';

    try {
        const res = await authFetch('/admin/upload_excel', {
            method: 'POST',
            body: fd,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Ошибка загрузки файла');
        }
        const json = await res.json();
        importData.cacheKey = json.cache_key;
        return json.cache_key;
    } catch (e) {
        alert('Ошибка загрузки файла: ' + e.message);
        return null;
    }
}

/**
 * "Apply changes" — incremental: delete removed, upsert added+modified.
 *
 * Three phases, each with its own progress bar segment:
 *   1. Deletions (0-20%)
 *   2. Upsert (20-95%)
 *   3. Hierarchy-cache invalidation (95-100%)
 */
export async function applyDiffChanges() {
    const { added, modified, deleted, folderChanges } = diffData;
    const materialChanges = added.length + modified.length + deleted.length;
    const folderChangesCount =
        folderChanges.added.length + folderChanges.modified.length + folderChanges.deleted.length;
    const totalChanges = materialChanges + folderChangesCount;

    if (totalChanges === 0) {
        alert('Нет изменений для применения.\n\nБаза данных уже актуальна!');
        closeModal('import');
        return;
    }

    let confirmMsg = '📋 Будут применены следующие изменения:\n\n';
    if (materialChanges > 0) {
        confirmMsg += `МАТЕРИАЛЫ:\n`;
        confirmMsg += `  + Добавлено: ${added.length}\n`;
        confirmMsg += `  ~ Изменено: ${modified.length}\n`;
        confirmMsg += `  - Удалено: ${deleted.length}\n\n`;
    }
    if (folderChangesCount > 0) {
        confirmMsg += `ПАПКИ (автоматически):\n`;
        confirmMsg += `  + Новых: ${folderChanges.added.length}\n`;
        confirmMsg += `  ~ Изменённых: ${folderChanges.modified.length}\n`;
        confirmMsg += `  - Удаляемых: ${folderChanges.deleted.length}\n\n`;
    }
    if (deleted.length > 0 || folderChanges.deleted.length > 0) {
        confirmMsg += `⚠️ ВНИМАНИЕ: Некоторые записи будут удалены!\n\n`;
    }
    confirmMsg += `Продолжить?`;

    if (!confirm(confirmMsg)) return;

    showImportStep('progress');
    els.importProgress.style.width = '0%';
    els.importStatusText.innerText = 'Применение изменений...';

    try {
        // Phase 1 — deletions
        if (deleted.length > 0) {
            els.importStatusText.innerText = `Удаление ${deleted.length} записей...`;
            const codesToDelete = deleted.map((r) => r.code);
            const batchSize = 100;
            for (let i = 0; i < codesToDelete.length; i += batchSize) {
                const batch = codesToDelete.slice(i, i + batchSize);
                const res = await fetch('/delete_batch_records', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        database: state.activeCollection,
                        codes: batch,
                    }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || 'Ошибка удаления записей');
                }
                const progress = ((i + batch.length) / codesToDelete.length) * 20;
                els.importProgress.style.width = `${progress}%`;
            }
        }
        els.importProgress.style.width = '20%';

        // Phase 2 — upsert via /admin/import
        const hierarchyCols = getOrderedSelection('hierarchy');

        const recordsToUpsert = [
            ...added.map((r) => ({
                code: r.code,
                description: r.description,
                hierarchy: hierarchyCols.length > 0 ? r.hierarchy : undefined,
                meta: r.meta || {},
            })),
            ...modified.map((r) => ({
                code: r.code,
                description: r.newDescription,
                hierarchy: hierarchyCols.length > 0 ? r.hierarchy : undefined,
                meta: {},
            })),
        ];

        const folderOnlyChanges = recordsToUpsert.length === 0
            && (folderChanges.added.length > 0
                || folderChanges.modified.length > 0
                || folderChanges.deleted.length > 0);

        if (folderOnlyChanges) {
            els.importStatusText.innerText = `Обновление папок: загрузка всех материалов...`;
            const allRecords = buildRecordsFromMapping();
            const payload = {
                collection_name: state.activeCollection,
                records: allRecords.map((r) => ({
                    code: r.code,
                    description: r.description,
                    hierarchy: hierarchyCols.length > 0 ? r.hierarchy : undefined,
                    meta: r.meta,
                })),
                recreate: false,
                folders_to_delete: folderChanges.deleted.map((f) => f.full_path),
            };
            const res = await authFetch('/admin/import', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Ошибка импорта записей');
            }
            const json = await res.json();
            els.importStatusText.innerText = 'Пересоздание папок каталога...';
            await pollJobUntilComplete(json.job_id, 20, 95);
        } else if (recordsToUpsert.length > 0) {
            els.importStatusText.innerText = `Загрузка ${recordsToUpsert.length} записей через импорт...`;
            const payload = {
                collection_name: state.activeCollection,
                records: recordsToUpsert,
                recreate: false,
                folders_to_delete: folderChanges.deleted.map((f) => f.full_path),
            };
            const res = await authFetch('/admin/import', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Ошибка импорта записей');
            }
            const json = await res.json();
            els.importStatusText.innerText = 'Обработка записей...';
            await pollJobUntilComplete(json.job_id, 20, 95);
        }

        els.importProgress.style.width = '95%';
        els.importStatusText.innerText = 'Обновление кэша...';

        try {
            await fetch(`/hierarchy/${state.activeCollection}/invalidate`, { method: 'POST' });
            console.log('✅ Кэш иерархии очищен');
        } catch (e) {
            console.warn('⚠️ Не удалось очистить кэш иерархии:', e);
        }

        els.importProgress.style.width = '100%';
        els.importStatusText.innerText = 'Завершено!';

        setTimeout(() => {
            let msg = `✅ Изменения применены!\n\n`;
            if (materialChanges > 0) {
                msg += `МАТЕРИАЛЫ:\n`;
                msg += `  Добавлено: ${added.length}\n`;
                msg += `  Обновлено: ${modified.length}\n`;
                msg += `  Удалено: ${deleted.length}\n\n`;
            }
            if (folderChangesCount > 0) {
                msg += `ПАПКИ (автоматически):\n`;
                msg += `  Новых: ${folderChanges.added.length}\n`;
                msg += `  Обновлено: ${folderChanges.modified.length}\n`;
                msg += `  Удалено: ${folderChanges.deleted.length}\n\n`;
            }
            msg += `Поля path_level_N сгенерированы для иерархического каталога.`;
            alert(msg);
            closeModal('import');
            loadCollections();
        }, 500);
    } catch (e) {
        console.error('❌ Ошибка применения изменений:', e);
        els.importStatusText.innerText = 'Ошибка!';
        alert('Ошибка применения изменений: ' + e.message);
    }
}
