/**
 * Apply changes flow ("Apply changes" button — incremental diff apply).
 *
 * Three phases, each with its own progress-bar segment:
 *   1. Deletions (0-20%)
 *   2. Upsert (20-95%)
 *   3. Hierarchy-cache invalidation (95-100%)
 *
 * Split out of the original run.js for module size management.
 */

import { state } from '../../state.js';
import { els } from '../../els.js';
import { authFetch } from '../../../shared/api.js';
import { diffData } from '../state.js';
import { buildRecordsFromMapping, getOrderedSelection } from '../mapping.js';
import { showImportStep } from '../wizard.js';
import { closeModal } from '../../modals.js';
import { loadCollections } from '../../collections/list.js';
import { pollJobUntilComplete } from '../jobs-poll.js';

/**
 * "Apply changes" — incremental: delete removed, upsert added+modified.
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
