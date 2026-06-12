/**
 * Full-overwrite upload flow ("Upload everything" button).
 *
 * For Excel uploads we already have a cache_key, so we send that
 * instead of the in-memory records (which would be 28 MB for 142k
 * rows). For paste-source imports we build the records here.
 *
 * Includes uploadExcelFileToServer() — a helper that uploads the
 * in-memory Excel file and returns its server-side cache_key.
 *
 * Split out of the original run.js for module size management.
 */

import { state } from '../../state.js';
import { els } from '../../els.js';
import { authFetch } from '../../../shared/api.js';
import { importData } from '../state.js';
import { buildRecordsFromMapping, getOrderedSelection } from '../mapping.js';
import { showImportStep } from '../wizard.js';
import { watchJob } from '../jobs-watch.js';
import { pollJob } from '../jobs-poll.js';

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
