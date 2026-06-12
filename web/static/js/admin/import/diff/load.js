/**
 * Load the full Excel data from the server cache.
 *
 * After a file is uploaded the server returns only a preview (first N
 * rows). For the diff/apply flow we need the whole thing, so we
 * fetch the full dataset by cache_key and overwrite importData.raw.
 */

import { els } from '../../els.js';
import { importData } from '../state.js';
import { authFetch } from '../../../shared/api.js';

/**
 * @returns {Promise<boolean>} true if the data was loaded (or there
 *   was no cache_key, in which case the paste-source raw data is
 *   used as-is), false on error.
 */
export async function loadFullExcelData() {
    const cacheKey = importData.cacheKey;
    if (!cacheKey) {
        console.log('Нет cacheKey — используем данные из state.importData.raw');
        return true;
    }

    try {
        console.log(`Загрузка всех данных из кэша: ${cacheKey}`);
        const response = await authFetch(`/admin/excel_data/${cacheKey}`);
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Ошибка загрузки' }));
            throw new Error(error.detail || 'Не удалось загрузить данные');
        }
        const data = await response.json();
        importData.raw = data.data;
        console.log(`✅ Загружено ${data.total_rows} строк из кэша`);
        return true;
    } catch (error) {
        console.error('Ошибка загрузки данных из кэша:', error);
        alert(`Ошибка загрузки данных: ${error.message}\n\nПопробуйте загрузить файл заново.`);
        return false;
    }
}

/* silence unused */
void els;
