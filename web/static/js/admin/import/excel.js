/**
 * Excel source — drag/drop a .xlsx/.xls, upload it to the server, and
 * use the returned cache_key when the import runs.
 *
 * The previous implementation re-rendered the dropzone HTML and
 * re-attached listeners on every reset. The new version preserves that
 * behaviour with a small helper that handles the re-attach.
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { importData } from './state.js';
import { getAuthHeaders } from '../../shared/api.js';
import { renderNumberedCheckboxes, renderPreviewTable, updateAllPreviews } from './preview.js';
import { showImportStep } from './wizard.js';

/**
 * Wire up the drag/drop zone and the file <input>.
 * Installed once at bootstrap.
 */
export function initExcelUpload() {
    const dropZone = document.getElementById('excelDropZone');
    const fileInput = document.getElementById('excelFileInput');
    const fileInfo = document.getElementById('excelFileInfo');
    const fileClear = document.getElementById('excelFileClear');
    const sheetSelect = document.getElementById('excelSheetSelect');

    if (!dropZone || !fileInput) return;

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-over');
    });
    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('drag-over');
    });
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
        const files = e.dataTransfer.files;
        if (files.length > 0) handleExcelFile(files[0]);
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) handleExcelFile(e.target.files[0]);
    });

    if (fileClear) {
        fileClear.addEventListener('click', () => {
            resetExcelUploadUI();
        });
    }

    if (sheetSelect) {
        sheetSelect.addEventListener('change', async () => {
            if (importData.excelFile) {
                await uploadExcelFile(importData.excelFile, sheetSelect.value);
            }
        });
    }
}

/**
 * Reset the dropzone to its initial state. Called by openImport() and
 * after a failed upload.
 */
export function resetExcelUploadUI() {
    const dropZone = document.getElementById('excelDropZone');
    const fileInput = document.getElementById('excelFileInput');
    const fileInfo = document.getElementById('excelFileInfo');
    const sheetSelector = document.getElementById('excelSheetSelector');

    if (fileInput) fileInput.value = '';
    if (fileInfo) fileInfo.classList.add('hidden');
    if (sheetSelector) sheetSelector.classList.add('hidden');

    if (dropZone) {
        dropZone.classList.remove('hidden');
        dropZone.innerHTML = `
            <i class="fas fa-file-excel"></i>
            <p>Перетащите Excel файл сюда</p>
            <span>или</span>
            <label for="excelFileInput" class="btn btn-outline" style="cursor: pointer;">
                <i class="fas fa-folder-open"></i> Выбрать файл
            </label>
            <input type="file" id="excelFileInput" accept=".xlsx,.xls" hidden>
        `;
        // Re-attach the change listener to the freshly-rendered <input>.
        const newFileInput = document.getElementById('excelFileInput');
        newFileInput?.addEventListener('change', (e) => {
            if (e.target.files.length > 0) handleExcelFile(e.target.files[0]);
        });
    }

    importData.excelData = null;
}

/**
 * Validate the file extension and kick off an upload.
 *
 * @param {File} file
 */
export async function handleExcelFile(file) {
    const validExtensions = ['.xlsx', '.xls'];
    const fileName = file.name.toLowerCase();
    const isValid = validExtensions.some((ext) => fileName.endsWith(ext));
    if (!isValid) {
        alert('Пожалуйста, выберите файл Excel (.xlsx или .xls)');
        return;
    }
    importData.excelFile = file;
    await uploadExcelFile(file);
}

/**
 * POST the file to /admin/upload_excel. On success, seed the
 * mapping step with the server-returned headers and preview.
 *
 * NOTE: We don't go through authFetch() here because we need to send
 * multipart/form-data, which means the browser must set the
 * Content-Type boundary itself — authFetch's default 'application/json'
 * header would break that. The auth header is attached explicitly.
 */
export async function uploadExcelFile(file, sheet = null) {
    const dropZone = document.getElementById('excelDropZone');
    const fileInfo = document.getElementById('excelFileInfo');
    const fileNameEl = document.getElementById('excelFileName');
    const fileStats = document.getElementById('excelFileStats');
    const sheetSelector = document.getElementById('excelSheetSelector');
    const sheetSelect = document.getElementById('excelSheetSelect');

    try {
        if (dropZone) {
            dropZone.innerHTML = '<i class="fas fa-spinner fa-spin"></i><p>Загрузка файла...</p>';
        }

        const formData = new FormData();
        formData.append('file', file);
        if (sheet) formData.append('sheet', sheet);

        const response = await fetch('/admin/upload_excel', {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${state.token}`,
            },
            body: formData,
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Ошибка загрузки' }));
            throw new Error(errorData.detail || 'Ошибка загрузки файла');
        }

        const data = await response.json();
        importData.excelData = data;
        importData.headers = data.headers;
        importData.raw = data.preview;
        importData.cacheKey = data.cache_key;
        importData.totalRows = data.total_rows;

        if (dropZone) dropZone.classList.add('hidden');
        if (fileInfo) {
            fileInfo.classList.remove('hidden');
            if (fileNameEl) fileNameEl.textContent = data.filename || file.name;
            if (fileStats) fileStats.textContent = `${data.total_rows} строк, ${data.headers.length} колонок`;
        }

        if (data.sheets && data.sheets.length > 1 && sheetSelector && sheetSelect) {
            sheetSelector.classList.remove('hidden');
            sheetSelect.innerHTML = data.sheets.map((s) =>
                `<option value="${s}" ${s === data.selected_sheet ? 'selected' : ''}>${s}</option>`,
            ).join('');
        }

        // Default selection — first column for code, as in the paste flow.
        importData.codeSelection = {};
        if (importData.headers.length > 0) {
            importData.codeSelection[importData.headers[0]] = 1;
        }
        importData.descSelection = {};
        importData.hierarchySelection = {};

        if (els.mapCodeCols) renderNumberedCheckboxes(els.mapCodeCols, importData.codeSelection, 'code');
        if (els.mapDescCols) renderNumberedCheckboxes(els.mapDescCols, importData.descSelection, 'desc');
        if (els.mapHierarchyCols) renderNumberedCheckboxes(els.mapHierarchyCols, importData.hierarchySelection, 'hierarchy');

        renderPreviewTable();
        updateAllPreviews();
        showImportStep('mapping');
    } catch (error) {
        console.error('Excel upload error:', error);
        alert(`Ошибка загрузки Excel: ${error.message}`);
        resetExcelUploadUI();
    }
}

/* silence unused */
void getAuthHeaders;
