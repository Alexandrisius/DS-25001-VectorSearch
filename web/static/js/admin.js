/**
 * KSR Matcher - Административная панель
 * 
 * Функциональность:
 * - Управление коллекциями (создание, удаление, настройка)
 * - Просмотр и редактирование данных (inline edit)
 * - Импорт данных из CSV/Excel (с маппингом колонок)
 * - Мониторинг фоновых задач
 * 
 * @author Alexandr
 * @version 2.0.0
 * @license MIT
 */

// === GLOBAL STATE ===
/**
 * Глобальное состояние приложения.
 * Хранит текущий токен, список коллекций, активный вид и т.д.
 */
const state = {
    /** @type {string|null} Токен аутентификации */
    token: localStorage.getItem('adminToken'),
    /** @type {Array} Список коллекций с метаданными */
    collections: [],
    /** @type {string} Текущий вид: 'collections' | 'jobs' | 'data' */
    currentView: 'collections',
    /** @type {string|null} Имя активной коллекции (для просмотра данных) */
    activeCollection: null,
    /** @type {number|null} ID интервала для опроса статуса задач */
    jobPoller: null,
    /** @type {string|null} Токен пагинации для загрузки данных */
    dataOffset: null,
    /** @type {Object} Данные для мастера импорта */
    importData: {
        raw: [],
        headers: [],
        // Состояние цифровых чек-боксов: { columnName: orderNumber (1-N) или 0 }
        codeSelection: {},      // Выбранные колонки для кода
        descSelection: {},      // Выбранные колонки для описания
        hierarchySelection: {}, // Выбранные колонки для иерархии
        codeSeparator: '.',     // Разделитель для склейки кода
        descSeparator: ' '      // Разделитель для склейки описания (по умолчанию пробел)
    },
    /** @type {Object} Результаты diff-анализа */
    diffData: {
        added: [],      // Новые записи материалов
        modified: [],   // Изменённые записи материалов
        deleted: [],    // Удалённые записи материалов
        unchanged: 0,   // Количество материалов без изменений
        existingRecords: {}, // Текущие записи материалов из базы {code: description}

        // === ПАПКИ ===
        folderChanges: {
            added: [],      // Новые папки [{full_path, leaf_name, items_count}]
            modified: [],   // Изменённые папки (изменилось количество материалов)
            deleted: []     // Удалённые папки (осиротевшие)
        },
        existingFolders: {} // Текущие папки из базы {full_path: {leaf_name, items_count}}
    },
    /** @type {string} Текущий таб в diff: 'added' | 'modified' | 'deleted' | 'folders' */
    diffActiveTab: 'added',
    /** @type {Array} Загруженные строки данных для таблицы */
    dataRows: [],
    /** @type {string|null} Колонка сортировки */
    sortColumn: null,
    /** @type {string} Направление сортировки: 'asc' | 'desc' */
    sortDirection: 'asc',
    /** @type {Array} Список колонок path_level_N в данных */
    pathLevelColumns: [],
    /** @type {boolean} Флаг наличия поля full_description в данных */
    hasFullDescription: false,

    // === НОВЫЕ ПОЛЯ v3 ===
    /** @type {Object} Ширины колонок {columnKey: width} */
    columnWidths: JSON.parse(localStorage.getItem('adminColumnWidths') || '{}'),
    /** @type {Array} Список доступных статусов записей */
    statuses: [],
    /** @type {string} Статус по умолчанию для новых записей */
    defaultStatus: 'active',
    /** @type {boolean} Флаг загрузки данных (для infinite scroll) */
    isLoadingData: false,
    /** @type {boolean} Флаг загрузки данных (для infinite scroll) */
    isLoadingData: false,
    /** @type {IntersectionObserver|null} Observer для infinite scroll */
    scrollObserver: null,
    /** @type {Array} Правила очистки данных */
    cleaningRules: []
};

// === DOM ELEMENTS ===
const els = {
    loginScreen: document.getElementById('loginScreen'),
    adminApp: document.getElementById('adminApp'),
    authPassword: document.getElementById('authPassword'),
    authBtn: document.getElementById('authBtn'),
    authError: document.getElementById('authError'),

    // Nav
    navLinks: document.querySelectorAll('.nav-item[data-view]'),
    pageTitle: document.getElementById('pageTitle'),
    headerActions: document.getElementById('headerActions'),
    logoutBtn: document.getElementById('logoutBtn'),
    contentBody: document.getElementById('contentBody'),

    // Views
    views: {
        collections: document.getElementById('viewCollections'),
        jobs: document.getElementById('viewJobs'),
        data: document.getElementById('viewData'),
        settings: document.getElementById('viewSettings')
    },

    // Collections
    collectionsGrid: document.getElementById('collectionsGrid'),

    // Data Table
    dataTable: document.getElementById('dataTable'),
    dataTableBody: document.getElementById('dataTableBody'),
    // loadMoreBtn заменён на infinite scroll
    scrollSentinel: document.getElementById('scrollSentinel'),
    infiniteScrollLoader: document.getElementById('infiniteScrollLoader'),

    // Jobs
    jobsTableBody: document.getElementById('jobsTableBody'),

    // Modals
    modals: {
        config: document.getElementById('configModal'),
        import: document.getElementById('importModal'),
        create: document.getElementById('createModal'),
        addRecord: document.getElementById('addRecordModal'),
        deleteConfirm: document.getElementById('deleteConfirmModal')
    },

    // Delete Confirmation
    deleteCollectionName: document.getElementById('deleteCollectionName'),
    deleteCollectionNameHint: document.getElementById('deleteCollectionNameHint'),
    deleteConfirmInput: document.getElementById('deleteConfirmInput'),
    confirmDeleteBtn: document.getElementById('confirmDeleteBtn'),

    // Config Form
    cfgName: document.getElementById('cfgName'),
    cfgCosine: document.getElementById('cfgCosine'),
    cfgRerank: document.getElementById('cfgRerank'),
    cfgVisible: document.getElementById('cfgVisible'),
    saveConfigBtn: document.getElementById('saveConfigBtn'),

    // Create Collection Form
    newCollId: document.getElementById('newCollId'),
    newCollName: document.getElementById('newCollName'),
    newCollCosine: document.getElementById('newCollCosine'),
    newCollRerank: document.getElementById('newCollRerank'),
    newCollVisible: document.getElementById('newCollVisible'),
    createCollBtn: document.getElementById('createCollBtn'),

    // Add Record Form
    newRecCode: document.getElementById('newRecCode'),
    newRecDesc: document.getElementById('newRecDesc'),
    saveRecBtn: document.getElementById('saveRecBtn'),

    // Import Wizard
    importTarget: document.getElementById('importTargetCollection'),
    pasteArea: document.getElementById('pasteArea'),

    // Новые панели с цифровыми чек-боксами
    mapCodeCols: document.getElementById('mapCodeCols'),
    mapDescCols: document.getElementById('mapDescCols'),
    mapHierarchyCols: document.getElementById('mapHierarchyCols'),

    // Разделители и превью
    codeSeparator: document.getElementById('codeSeparator'),
    descSeparator: document.getElementById('descSeparator'),  // Новый: разделитель описания
    codePreview: document.getElementById('codePreview'),
    descPreview: document.getElementById('descPreview'),
    hierarchyPreview: document.getElementById('hierarchyPreview'),

    importProgress: document.getElementById('importProgress'),
    importStatusText: document.getElementById('importStatusText'),

    // Шаги визарда (теперь 4 шага: paste, mapping, diff, progress)
    importSteps: {
        paste: document.getElementById('importStep1'),
        mapping: document.getElementById('importStep2'),
        diff: document.getElementById('importStepDiff'),
        progress: document.getElementById('importStep3')
    },

    // Кнопки визарда
    importBtns: {
        back: document.getElementById('importBackBtn'),
        next: document.getElementById('importNextBtn'),
        compare: document.getElementById('importCompareBtn'),
        upload: document.getElementById('importUploadBtn'),
        apply: document.getElementById('importApplyBtn')
    },

    // Diff элементы
    diffSummary: document.getElementById('diffSummary'),
    diffAddedCount: document.getElementById('diffAddedCount'),
    diffModifiedCount: document.getElementById('diffModifiedCount'),
    diffDeletedCount: document.getElementById('diffDeletedCount'),
    diffFoldersCount: document.getElementById('diffFoldersCount'),
    diffAddedBadge: document.getElementById('diffAddedBadge'),
    diffModifiedBadge: document.getElementById('diffModifiedBadge'),
    diffDeletedBadge: document.getElementById('diffDeletedBadge'),
    diffFoldersBadge: document.getElementById('diffFoldersBadge'),
    diffDeleteWarning: document.getElementById('diffDeleteWarning'),
    diffTableBody: document.getElementById('diffTableBody'),
    diffEmpty: document.getElementById('diffEmpty'),
    diffLoading: document.getElementById('diffLoading'),

    // Preview elements
    previewTable: document.getElementById('previewTable'),
    previewHead: document.getElementById('previewHead'),
    previewBody: document.getElementById('previewBody'),
    previewCount: document.getElementById('previewCount')
};

// === INITIALIZATION ===
document.addEventListener('DOMContentLoaded', () => {
    checkMobileDevice();
    initAuth();
    initNavigation();
    initModals();
    initImportWizard();
    initCreateCollection();
    initAddRecord();
    initDiffTabs();
    initSorting();
    initModalResize();
    initStatusDropdowns(); // Инициализация кастомных dropdown статусов (делегирование событий)
    loadStatuses(); // Загрузка статусов при инициализации
    initSettingsPage(); // Инициализация страницы настроек
    initOpenRouterSettings(); // Инициализация настроек OpenRouter
    loadOpenRouterSettings(); // Загрузка настроек OpenRouter
    loadCleaningRules();      // Загрузка правил очистки
});

/**
 * Загрузка списка статусов из конфигурации
 */
async function loadStatuses() {
    try {
        const res = await fetch('/admin/statuses');
        if (res.ok) {
            const data = await res.json();
            state.statuses = data.statuses || [];
            state.defaultStatus = data.default_status || 'active';
            console.log('✅ Статусы загружены:', state.statuses.length);
        }
    } catch (e) {
        console.warn('⚠️ Не удалось загрузить статусы:', e);
        // Используем статусы по умолчанию
        state.statuses = [
            { id: 'active', label: 'Активная', color: '#10b981' },
            { id: 'draft', label: 'Черновик', color: '#f59e0b' },
            { id: 'deprecated', label: 'Устаревшая', color: '#ef4444' }
        ];
    }
}

// === SETTINGS PAGE (Страница настроек) ===

/**
 * Рендеринг списка статусов на странице настроек.
 * 
 * УЛУЧШЕНИЯ v2:
 * - Современный дизайн карточек с цветной полосой слева
 * - Большой цветовой превью с иконкой редактирования
 * - ID статуса в виде badge
 * - Плавные анимации
 */
function renderStatusesSettings() {
    const container = document.getElementById('statusesList');
    const defaultSelect = document.getElementById('defaultStatusSelect');

    if (!container || !defaultSelect) return;

    // Рендерим список статусов с новым дизайном
    container.innerHTML = state.statuses.map(status => `
        <div class="status-item" data-status-id="${status.id}" style="--status-color: ${status.color};">
            <div class="status-color-preview" style="background: ${status.color};" title="Нажмите для изменения цвета">
                <i class="fas fa-palette"></i>
                <input type="color" class="status-color-picker" value="${status.color}">
            </div>
            <div class="status-content">
                <div class="status-id-badge">
                    <i class="fas fa-hashtag"></i>
                    ${status.id}
                </div>
                <input type="text" class="status-label-input" value="${status.label}" placeholder="Название статуса">
            </div>
            <button class="btn-remove-status" title="Удалить статус">
                <i class="fas fa-trash"></i>
            </button>
        </div>
    `).join('');

    // Рендерим select для статуса по умолчанию
    defaultSelect.innerHTML = state.statuses.map(status => `
        <option value="${status.id}" ${status.id === state.defaultStatus ? 'selected' : ''}>
            ${status.label}
        </option>
    `).join('');

    // Привязываем обработчики изменения цвета
    container.querySelectorAll('.status-color-picker').forEach(picker => {
        picker.addEventListener('input', (e) => {
            const item = e.target.closest('.status-item');
            const preview = item.querySelector('.status-color-preview');
            const newColor = e.target.value;

            // Обновляем превью и CSS переменную
            preview.style.background = newColor;
            item.style.setProperty('--status-color', newColor);
        });
    });

    // Привязываем обработчики удаления
    container.querySelectorAll('.btn-remove-status').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const item = e.target.closest('.status-item');
            const statusId = item.dataset.statusId;

            // Нельзя удалить статус по умолчанию
            if (statusId === state.defaultStatus) {
                alert('Нельзя удалить статус по умолчанию. Сначала выберите другой статус по умолчанию.');
                return;
            }

            // Нельзя удалить последний статус
            if (state.statuses.length <= 1) {
                alert('Должен остаться хотя бы один статус.');
                return;
            }

            // Анимация удаления
            item.style.opacity = '0';
            item.style.transform = 'translateX(-20px)';

            setTimeout(() => {
                // Удаляем из массива
                state.statuses = state.statuses.filter(s => s.id !== statusId);
                renderStatusesSettings();
            }, 200);
        });
    });
}

// === CLEANING RULES (Правила очистки) ===

/**
 * Загрузка правил очистки с сервера
 */
async function loadCleaningRules() {
    try {
        // Используем authFetch если возможно, или обычный fetch
        const fetchFunc = typeof authFetch === 'function' ? authFetch : fetch;

        const res = await fetchFunc('/admin/cleaning_rules');

        if (res.ok) {
            const data = await res.json();
            state.cleaningRules = data.rules || [];
            console.log(`🧹 Загружено ${state.cleaningRules.length} правил очистки`);
        } else {
            console.error(`❌ Ошибка загрузки правил: ${res.status}`);
        }
    } catch (e) {
        console.error('❌ Исключение при загрузке правил очистки:', e);
    }
}

/**
 * Применение правил очистки к строке
 * @param {string} text - Исходный текст
 * @param {string} columnType - Тип колонки ('hierarchy' | 'description' | 'code')
 * @returns {string} Очищенный текст
 */
function applyCleaningRules(text, columnType = null) {
    if (!text || typeof text !== 'string') return text;

    let result = text;

    // Применяем правила
    if (state.cleaningRules && state.cleaningRules.length > 0) {
        for (const rule of state.cleaningRules) {
            if (!rule.enabled) continue;

            // Проверка apply_to_columns
            // В JS логике мы используем типы колонок ('hierarchy', 'description') вместо имен
            // Если правило применяется ко всем ("*") или к конкретному типу
            const applyTo = rule.apply_to_columns || ["*"];

            // Если правило глобальное ("*") или тип колонок совпадает с одним из разрешенных
            // (можно расширить логику, если apply_to_columns содержит конкретные имена колонок из Excel,
            // но здесь мы знаем только семантический тип: иерархия или описание)
            const isApplicable = applyTo.includes("*") ||
                (columnType && applyTo.some(col => col.toLowerCase() === columnType.toLowerCase()));

            if (!isApplicable) continue;

            try {
                // ПРОВЕРКА REGEX
                // Сервер передает паттерн как строку. В JSON слэши экранированы.
                // new RegExp создаст правильный регекс.
                const regex = new RegExp(rule.pattern, 'g');

                if (regex.test(result)) {
                    result = result.replace(regex, rule.replacement || '');
                }
            } catch (e) {
                console.warn(`❌ Invalid regex in rule '${rule.name}':`, e);
            }
        }
    }

    return result.trim();
}

/**
 * Инициализация страницы настроек.
 * 
 * УЛУЧШЕНИЯ v2:
 * - Поддержка превью цвета для нового статуса
 * - Улучшенная валидация
 * - Плавные анимации
 */
function initSettingsPage() {
    const addBtn = document.getElementById('addStatusBtn');
    const saveBtn = document.getElementById('saveStatusesBtn');
    const colorInput = document.getElementById('newStatusColor');
    const colorPreview = document.getElementById('newStatusColorPreview');

    // Обновляем превью цвета при изменении
    if (colorInput && colorPreview) {
        colorInput.addEventListener('input', (e) => {
            colorPreview.style.background = e.target.value;
        });
    }

    if (addBtn) {
        addBtn.addEventListener('click', () => {
            const idInput = document.getElementById('newStatusId');
            const labelInput = document.getElementById('newStatusLabel');
            const colorInput = document.getElementById('newStatusColor');
            const colorPreview = document.getElementById('newStatusColorPreview');

            const id = idInput.value.trim().toLowerCase().replace(/\s+/g, '_');
            const label = labelInput.value.trim();
            const color = colorInput.value;

            if (!id || !label) {
                // Подсвечиваем пустые поля
                if (!id) idInput.style.borderColor = 'var(--adm-danger)';
                if (!label) labelInput.style.borderColor = 'var(--adm-danger)';

                setTimeout(() => {
                    idInput.style.borderColor = '';
                    labelInput.style.borderColor = '';
                }, 2000);

                return;
            }

            // Проверяем уникальность ID
            if (state.statuses.some(s => s.id === id)) {
                idInput.style.borderColor = 'var(--adm-danger)';
                idInput.placeholder = 'ID уже существует!';

                setTimeout(() => {
                    idInput.style.borderColor = '';
                    idInput.placeholder = 'ID (review, pending...)';
                }, 2000);

                return;
            }

            // Добавляем новый статус
            state.statuses.push({ id, label, color });

            // Очищаем поля с анимацией
            idInput.value = '';
            labelInput.value = '';
            colorInput.value = '#6366f1';
            if (colorPreview) colorPreview.style.background = '#6366f1';

            // Перерисовываем список
            renderStatusesSettings();

            // Фокус на ID для быстрого добавления следующего
            idInput.focus();
        });
    }

    if (saveBtn) {
        saveBtn.addEventListener('click', async () => {
            // Собираем актуальные данные из DOM
            const container = document.getElementById('statusesList');
            const defaultSelect = document.getElementById('defaultStatusSelect');

            const updatedStatuses = [];
            container.querySelectorAll('.status-item').forEach(item => {
                const id = item.dataset.statusId;
                const label = item.querySelector('.status-label-input').value.trim();
                const color = item.querySelector('.status-color-picker').value;

                if (id && label) {
                    updatedStatuses.push({ id, label, color });
                }
            });

            const defaultStatus = defaultSelect.value;

            // Показываем индикатор загрузки
            const originalText = saveBtn.innerHTML;
            saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Сохранение...';
            saveBtn.disabled = true;

            try {
                const res = await authFetch('/admin/statuses', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        statuses: updatedStatuses,
                        default_status: defaultStatus
                    })
                });

                if (res.ok) {
                    const data = await res.json();
                    state.statuses = data.statuses;
                    state.defaultStatus = data.default_status;

                    // Показываем успех
                    saveBtn.innerHTML = '<i class="fas fa-check"></i> Сохранено!';
                    saveBtn.style.background = 'var(--adm-success)';

                    setTimeout(() => {
                        saveBtn.innerHTML = originalText;
                        saveBtn.style.background = '';
                        saveBtn.disabled = false;
                    }, 2000);
                } else {
                    const err = await res.json();
                    throw new Error(err.detail || 'Не удалось сохранить');
                }
            } catch (e) {
                console.error('Ошибка сохранения статусов:', e);

                // Показываем ошибку
                saveBtn.innerHTML = '<i class="fas fa-times"></i> Ошибка';
                saveBtn.style.background = 'var(--adm-danger)';

                setTimeout(() => {
                    saveBtn.innerHTML = originalText;
                    saveBtn.style.background = '';
                    saveBtn.disabled = false;
                }, 2000);
            }
        });
    }
}


// === LLM API SETTINGS (OpenRouter / OpenAI-совместимый endpoint) ===

/**
 * Глобальное состояние настроек LLM API
 */
const openrouterState = {
    enabled: false,
    apiKey: '',
    apiKeySet: false,
    baseUrl: '',
    modelEmbed: 'qwen/qwen3-embedding-4b',
    modelRerank: 'cohere/rerank-4-pro',
    batch_size: 10,
    max_workers: 3,
    embedTest: { status: 'idle', message: '' },
    rerankTest: { status: 'idle', message: '' }
};

/**
 * Загрузка настроек LLM API при старте.
 */
async function loadOpenRouterSettings() {
    try {
        const res = await fetch('/admin/openrouter-settings');
        if (res.ok) {
            const data = await res.json();
            openrouterState.enabled = data.enabled === true;
            openrouterState.apiKeySet = data.api_key_set === true;
            openrouterState.baseUrl = data.base_url || '';
            openrouterState.modelEmbed = data.model_embed || 'qwen/qwen3-embedding-4b';
            openrouterState.modelRerank = data.model_rerank || 'cohere/rerank-4-pro';
            openrouterState.batch_size = data.batch_size || 10;
            openrouterState.max_workers = data.max_workers || 3;

            updateOpenRouterUI();
            console.log('LLM API settings loaded:', {
                modelEmbed: openrouterState.modelEmbed,
                modelRerank: openrouterState.modelRerank,
                baseUrl: openrouterState.baseUrl
            });
        } else {
            console.warn('Failed to load LLM settings, status:', res.status);
        }
    } catch (e) {
        console.warn('Failed to load LLM API settings:', e);
    }
}

/**
 * Обновление UI на основе состояния.
 */
function updateOpenRouterUI() {
    const enabledCheckbox = document.getElementById('openrouterEnabled');
    const apiKeyInput = document.getElementById('openrouterApiKey');
    const baseUrlInput = document.getElementById('openrouterBaseUrl');
    const modelEmbedInput = document.getElementById('openrouterModel');
    const modelRerankInput = document.getElementById('openrouterRerankModel');

    if (enabledCheckbox) {
        enabledCheckbox.checked = openrouterState.enabled;
    }

    if (apiKeyInput && openrouterState.apiKeySet) {
        apiKeyInput.placeholder = '••••••••••••••••';
    }

    if (baseUrlInput) {
        baseUrlInput.value = openrouterState.baseUrl || '';
    }

    if (modelEmbedInput) {
        modelEmbedInput.value = openrouterState.modelEmbed || '';
    }

    if (modelRerankInput) {
        modelRerankInput.value = openrouterState.modelRerank || '';
    }

    const batchSizeInput = document.getElementById('openrouterBatchSize');
    const maxWorkersInput = document.getElementById('openrouterMaxWorkers');
    if (batchSizeInput) {
        batchSizeInput.value = openrouterState.batch_size || 10;
    }
    if (maxWorkersInput) {
        maxWorkersInput.value = openrouterState.max_workers || 3;
    }

    // Обновляем модель в статусных блоках
    updateModelDisplay('Embed', openrouterState.modelEmbed, openrouterState.embedTest);
    updateModelDisplay('Rerank', openrouterState.modelRerank, openrouterState.rerankTest);
}

function updateModelDisplay(kind, model, testResult) {
    const isEmbed = kind === 'Embed';
    const modelEl = document.getElementById(isEmbed ? 'openrouterEmbedModel' : 'openrouterRerankModelText');
    const msgEl = document.getElementById(isEmbed ? 'openrouterEmbedMessage' : 'openrouterRerankMessage');
    const indEl = document.getElementById(isEmbed ? 'openrouterEmbedIndicator' : 'openrouterRerankIndicator');

    if (modelEl) {
        modelEl.textContent = model || '—';
    }
    if (msgEl) {
        if (!openrouterState.enabled) {
            msgEl.textContent = 'Провайдер выключен';
            msgEl.className = 'status-message';
        } else if (!openrouterState.apiKeySet) {
            msgEl.textContent = 'API ключ не задан';
            msgEl.className = 'status-message';
        } else if (testResult && testResult.status && testResult.status !== 'idle') {
            msgEl.textContent = testResult.message || '';
            msgEl.className = 'status-message ' + (testResult.status === 'success' ? 'is-success' : 'is-error');
        } else {
            msgEl.textContent = 'Готов к проверке';
            msgEl.className = 'status-message';
        }
    }
    if (indEl) {
        const i = indEl.querySelector('i');
        if (!i) return;
        if (!openrouterState.enabled || !openrouterState.apiKeySet) {
            indEl.className = 'status-indicator status-inactive';
            i.className = 'fas fa-circle';
        } else if (testResult && testResult.status === 'success') {
            indEl.className = 'status-indicator status-success';
            i.className = 'fas fa-check-circle';
        } else if (testResult && testResult.status === 'error') {
            indEl.className = 'status-indicator status-error';
            i.className = 'fas fa-times-circle';
        } else {
            indEl.className = 'status-indicator status-configured';
            i.className = 'fas fa-circle';
        }
    }
}

/**
 * Инициализация страницы настроек LLM API.
 */
function initOpenRouterSettings() {
    const saveBtn = document.getElementById('saveOpenrouterBtn');
    const testBtn = document.getElementById('testOpenrouterBtn');
    const toggleVisibilityBtn = document.getElementById('toggleApiKeyVisibility');
    const apiKeyInput = document.getElementById('openrouterApiKey');

    if (toggleVisibilityBtn && apiKeyInput) {
        toggleVisibilityBtn.addEventListener('click', () => {
            const type = apiKeyInput.type === 'password' ? 'text' : 'password';
            apiKeyInput.type = type;
            const icon = toggleVisibilityBtn.querySelector('i');
            if (icon) {
                icon.className = type === 'password' ? 'fas fa-eye' : 'fas fa-eye-slash';
            }
        });
    }

    if (saveBtn) {
        saveBtn.addEventListener('click', saveOpenRouterSettings);
    }

    if (testBtn) {
        testBtn.addEventListener('click', testOpenRouterConnection);
    }
}

/**
 * Сохранение настроек LLM API.
 */
async function saveOpenRouterSettings() {
    const saveBtn = document.getElementById('saveOpenrouterBtn');
    if (!saveBtn) return;

    const enabledCheckbox = document.getElementById('openrouterEnabled');
    const apiKeyInput = document.getElementById('openrouterApiKey');
    const baseUrlInput = document.getElementById('openrouterBaseUrl');
    const modelEmbedInput = document.getElementById('openrouterModel');
    const modelRerankInput = document.getElementById('openrouterRerankModel');
    const batchSizeInput = document.getElementById('openrouterBatchSize');
    const maxWorkersInput = document.getElementById('openrouterMaxWorkers');

    const enabled = enabledCheckbox ? enabledCheckbox.checked : false;
    const apiKey = apiKeyInput ? apiKeyInput.value.trim() : '';
    const baseUrl = baseUrlInput ? baseUrlInput.value.trim() : '';
    const modelEmbed = modelEmbedInput ? modelEmbedInput.value.trim() : 'qwen/qwen3-embedding-4b';
    const modelRerank = modelRerankInput ? modelRerankInput.value.trim() : 'cohere/rerank-4-pro';
    const batch_size = batchSizeInput ? parseInt(batchSizeInput.value) || 10 : 10;
    const max_workers = maxWorkersInput ? parseInt(maxWorkersInput.value) || 3 : 3;

    const originalText = saveBtn.innerHTML;
    saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Сохранение...';
    saveBtn.disabled = true;

    try {
        const res = await authFetch('/admin/openrouter-settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                enabled: enabled,
                api_key: apiKey,
                base_url: baseUrl || null,
                model_embed: modelEmbed,
                model_rerank: modelRerank,
                batch_size: batch_size,
                max_workers: max_workers
            })
        });

        if (res.ok) {
            const data = await res.json();
            openrouterState.enabled = data.enabled === true;
            openrouterState.apiKeySet = data.api_key_set === true;
            openrouterState.baseUrl = data.base_url || '';
            openrouterState.modelEmbed = data.model_embed || '';
            openrouterState.modelRerank = data.model_rerank || '';
            openrouterState.batch_size = data.batch_size || 10;
            openrouterState.max_workers = data.max_workers || 3;

            if (apiKeyInput && apiKey) {
                apiKeyInput.value = '';
                apiKeyInput.placeholder = '••••••••••••••••';
            }

            updateOpenRouterUI();

            saveBtn.innerHTML = '<i class="fas fa-check"></i> Сохранено!';
            saveBtn.style.background = 'var(--adm-success)';

            setTimeout(() => {
                saveBtn.innerHTML = originalText;
                saveBtn.style.background = '';
                saveBtn.disabled = false;
            }, 2000);
        } else {
            const err = await res.json();
            throw new Error(err.detail || 'Не удалось сохранить');
        }
    } catch (e) {
        console.error('Ошибка сохранения настроек LLM API:', e);
        saveBtn.innerHTML = '<i class="fas fa-times"></i> Ошибка';
        saveBtn.style.background = 'var(--adm-danger)';

        setTimeout(() => {
            saveBtn.innerHTML = originalText;
            saveBtn.style.background = '';
            saveBtn.disabled = false;
        }, 2000);
    }
}

/**
 * Тестирование подключения к OpenRouter API.
 * Проверяет ОБА endpoint: embeddings и rerank.
 */
async function testOpenRouterConnection() {
    const testBtn = document.getElementById('testOpenrouterBtn');
    if (!testBtn) return;

    const originalText = testBtn.innerHTML;
    testBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Проверка...';
    testBtn.disabled = true;

    // Показываем "проверка" для обоих
    openrouterState.embedTest = { status: 'testing', message: 'Проверка...' };
    openrouterState.rerankTest = { status: 'testing', message: 'Проверка...' };
    updateOpenRouterUI();

    try {
        const res = await authFetch('/admin/openrouter-test', {
            method: 'POST'
        });

        const data = await res.json();

        // Обрабатываем embed
        if (data.embed) {
            openrouterState.embedTest = {
                status: data.embed.status,
                message: data.embed.message || ''
            };
        }
        // Обрабатываем rerank
        if (data.rerank) {
            openrouterState.rerankTest = {
                status: data.rerank.status,
                message: data.rerank.message || ''
            };
        }

        // Обновляем UI
        updateOpenRouterUI();

        // Кнопка — общий статус
        if (data.status === 'success') {
            testBtn.innerHTML = '<i class="fas fa-check"></i> Оба OK';
            testBtn.style.background = 'var(--adm-success)';
            testBtn.style.borderColor = 'var(--adm-success)';
            testBtn.style.color = 'white';
        } else {
            testBtn.innerHTML = '<i class="fas fa-times"></i> Есть ошибки';
            testBtn.style.background = 'var(--adm-danger)';
            testBtn.style.borderColor = 'var(--adm-danger)';
            testBtn.style.color = 'white';
        }

        setTimeout(() => {
            testBtn.innerHTML = originalText;
            testBtn.style.background = '';
            testBtn.style.borderColor = '';
            testBtn.style.color = '';
            testBtn.disabled = false;
        }, 3000);

    } catch (e) {
        console.error('Ошибка тестирования OpenRouter:', e);
        openrouterState.embedTest = { status: 'error', message: 'Ошибка сети: ' + e.message };
        openrouterState.rerankTest = { status: 'error', message: 'Ошибка сети: ' + e.message };
        updateOpenRouterUI();

        testBtn.innerHTML = '<i class="fas fa-times"></i> Ошибка';
        testBtn.style.background = 'var(--adm-danger)';
        testBtn.style.borderColor = 'var(--adm-danger)';
        testBtn.style.color = 'white';

        setTimeout(() => {
            testBtn.innerHTML = originalText;
            testBtn.style.background = '';
            testBtn.style.borderColor = '';
            testBtn.style.color = '';
            testBtn.disabled = false;
        }, 3000);
    }
}


/**
 * Проверка мобильного устройства и показ предупреждения.
 * Показывает overlay если ширина экрана меньше 768px.
 */
function checkMobileDevice() {
    const mobileWarning = document.getElementById('mobileWarning');
    const closeBtn = document.getElementById('mobileWarningClose');

    if (!mobileWarning || !closeBtn) return;

    // Проверяем ширину экрана
    if (window.innerWidth < 768) {
        // Проверяем, не закрывал ли пользователь уже это предупреждение
        const dismissed = sessionStorage.getItem('adminMobileWarningDismissed');

        if (!dismissed) {
            mobileWarning.classList.remove('hidden');
        }
    }

    // Обработчик закрытия
    closeBtn.addEventListener('click', () => {
        mobileWarning.classList.add('hidden');
        sessionStorage.setItem('adminMobileWarningDismissed', 'true');
    });
}

// === AUTHENTICATION ===

/**
 * Инициализация аутентификации.
 * Проверяет сохранённый токен и настраивает обработчики.
 */
function initAuth() {
    // Если есть сохранённый токен — валидируем через API.
    // Пока идёт валидация — показываем splash (НЕ форму входа),
    // иначе пользователь видит форму логина на 100-500мс ("flash").
    if (state.token) {
        // loginScreen скрыт, authSplash виден (по умолчанию)
        validateToken().then(valid => {
            if (valid) {
                showApp();
            } else {
                // Токен невалиден - очищаем и показываем форму входа
                logout();
            }
        });
    } else {
        // Токена нет — сразу показываем форму входа
        els.loginScreen.classList.remove('hidden');
        els.authSplash.classList.add('hidden');
    }

    els.authBtn.addEventListener('click', attemptLogin);
    els.authPassword.addEventListener('keyup', (e) => {
        if (e.key === 'Enter') attemptLogin();
    });

    els.logoutBtn.addEventListener('click', logout);
}

/**
 * Проверка валидности JWT токена через API запрос.
 * @returns {Promise<boolean>} True если токен валиден.
 */
async function validateToken() {
    if (!state.token) return false;

    try {
        const res = await fetch('/admin/collections', {
            headers: getAuthHeaders()
        });
        return res.ok;
    } catch (e) {
        return false;
    }
}

/**
 * Получение заголовков авторизации для API запросов.
 * @returns {Object} Объект заголовков с Authorization Bearer token.
 */
function getAuthHeaders() {
    return {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${state.token}`
    };
}

/**
 * Выполнение авторизованного API запроса.
 * Автоматически добавляет JWT токен и обрабатывает ошибки авторизации.
 * 
 * @param {string} url - URL эндпоинта
 * @param {Object} options - Опции fetch (method, body, etc.)
 * @returns {Promise<Response>} Ответ сервера
 * @throws {Error} При ошибке авторизации выполняет logout
 */
async function authFetch(url, options = {}) {
    // Добавляем заголовки авторизации
    const headers = {
        ...getAuthHeaders(),
        ...(options.headers || {})
    };

    const res = await fetch(url, {
        ...options,
        headers
    });

    // Обработка ошибок авторизации
    if (res.status === 401) {
        console.warn('🔒 JWT токен истёк или невалиден');
        alert('Сессия истекла. Пожалуйста, войдите снова.');
        logout();
        throw new Error('Unauthorized');
    }

    return res;
}

/**
 * Выход из админ-панели.
 * Очищает токен и перезагружает страницу.
 */
function logout() {
    state.token = null;
    localStorage.removeItem('adminToken');
    location.reload();
}

/**
 * Попытка входа в админ-панель.
 * При успехе сохраняет JWT токен.
 */
async function attemptLogin() {
    const pwd = els.authPassword.value;

    // Блокируем кнопку на время запроса
    els.authBtn.disabled = true;
    els.authBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Вход...';
    els.authError.classList.add('hidden');

    try {
        const res = await fetch('/admin/auth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: pwd })
        });

        if (res.ok) {
            const data = await res.json();

            // Сохраняем JWT токен
            state.token = data.token;
            localStorage.setItem('adminToken', data.token);

            // Логируем время истечения
            const expiresHours = Math.round(data.expires_in / 3600);
            console.log(`✅ Вход выполнен. Токен действителен ${expiresHours} часов.`);

            showApp();
        } else {
            const error = await res.json();

            // Обработка rate limit
            if (res.status === 429) {
                els.authError.textContent = error.detail || 'Слишком много попыток. Подождите.';
            } else {
                els.authError.textContent = error.detail || 'Неверный пароль';
            }

            els.authError.classList.remove('hidden');
        }
    } catch (e) {
        console.error('Login error:', e);
        els.authError.textContent = 'Ошибка подключения к серверу';
        els.authError.classList.remove('hidden');
    } finally {
        els.authBtn.disabled = false;
        els.authBtn.innerHTML = 'Войти';
    }
}

function showApp() {
    els.loginScreen.classList.add('hidden');
    els.authSplash.classList.add('hidden');
    els.adminApp.classList.remove('hidden');
    switchView('collections');
    startJobPoller();
}

// === NAVIGATION ===
function initNavigation() {
    els.navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const view = link.dataset.view;
            switchView(view);
        });
    });
}

function switchView(viewName) {
    state.currentView = viewName;

    // Update Sidebar Active State
    els.navLinks.forEach(l => {
        if (l.dataset.view === viewName) l.classList.add('active');
        else l.classList.remove('active');
    });

    // Hide all views
    Object.values(els.views).forEach(v => {
        if (v) v.classList.add('hidden');
    });

    // Show target view
    if (els.views[viewName]) {
        els.views[viewName].classList.remove('hidden');
    }

    // Update Header & Data
    els.headerActions.innerHTML = '';

    if (viewName === 'collections') {
        els.pageTitle.innerText = 'Коллекции';

        const createBtn = document.createElement('button');
        createBtn.className = 'btn btn-primary';
        createBtn.innerHTML = '<i class="fas fa-plus"></i> Создать коллекцию';
        createBtn.onclick = () => openModal('create');
        els.headerActions.appendChild(createBtn);

        loadCollections();
    } else if (viewName === 'jobs') {
        els.pageTitle.innerText = 'Фоновые задачи';
        loadJobs();
    } else if (viewName === 'data') {
        els.pageTitle.innerText = `Данные: ${state.activeCollection}`;

        const backBtn = document.createElement('button');
        backBtn.className = 'btn btn-outline';
        backBtn.innerHTML = '<i class="fas fa-arrow-left"></i> Назад';
        backBtn.onclick = () => switchView('collections');
        els.headerActions.appendChild(backBtn);

        const addBtn = document.createElement('button');
        addBtn.className = 'btn btn-primary';
        addBtn.innerHTML = '<i class="fas fa-plus"></i> Добавить запись';
        addBtn.style.marginLeft = '10px';
        addBtn.onclick = () => {
            els.newRecCode.value = '';
            els.newRecDesc.value = '';
            openModal('addRecord');
        };
        els.headerActions.appendChild(addBtn);
    } else if (viewName === 'settings') {
        els.pageTitle.innerText = 'Настройки';
        renderStatusesSettings();
    }
}

// === COLLECTIONS ===
async function loadCollections() {
    try {
        const res = await authFetch('/admin/collections');
        const data = await res.json();
        state.collections = data.collections;
        renderCollectionsGrid();
    } catch (e) {
        if (e.message !== 'Unauthorized') {
            console.error('Failed to load collections:', e);
        }
    }
}

function renderCollectionsGrid() {
    els.collectionsGrid.innerHTML = '';

    state.collections.forEach(c => {
        const isVisible = c.visible !== undefined ? c.visible : true;
        const lastUpd = c.last_updated || 'Не обновлялась';
        const recordCount = c.record_count || 0;
        const isLocked = c.locked || false;

        const card = document.createElement('div');
        card.className = 'collection-card';
        card.innerHTML = `
            <div class="card-header">
                <div class="card-title">
                    ${isLocked ? '<i class="fas fa-lock" title="Защищённая коллекция" style="color: var(--adm-warning); margin-right: 6px;"></i>' : ''}
                    ${c.name}
                </div>
                <span class="status-badge ${isVisible ? 'status-visible' : 'status-hidden'}">
                    ${isVisible ? '🟢 Видимая' : '🔴 Скрытая'}
                </span>
            </div>
            
            <p style="color:var(--adm-text-sec); font-size:0.85rem; margin-bottom:15px; flex:1">
                ${c.description || 'Без описания'}
            </p>
            
            <div class="card-stats">
                <div class="stat-item">
                    Записей <strong>${recordCount.toLocaleString()}</strong>
                </div>
                <div class="stat-item">
                    Обновлено <strong>${lastUpd}</strong>
                </div>
            </div>

            <div class="card-actions">
                <button class="btn btn-outline" onclick="openConfig('${c.name}')">
                    <i class="fas fa-cog"></i> Настройки
                </button>
                <button class="btn btn-outline" onclick="openDataView('${c.name}')">
                    <i class="fas fa-table"></i> Данные
                </button>
                <button class="btn btn-outline" onclick="openImport('${c.name}')">
                    <i class="fas fa-upload"></i> Импорт
                </button>
                <button class="btn btn-danger ${isLocked ? 'btn-locked' : ''}" onclick="deleteCollection('${c.name}', ${isLocked})" ${isLocked ? 'title="Защищённая коллекция"' : ''}>
                    <i class="fas fa-${isLocked ? 'lock' : 'trash'}"></i>
                </button>
            </div>
        `;
        els.collectionsGrid.appendChild(card);
    });
}

// === DELETE COLLECTION WITH CONFIRMATION ===
// Храним имя коллекции для удаления
let pendingDeleteCollection = null;

window.deleteCollection = (name, isLocked = false) => {
    // Проверяем защиту коллекции
    if (isLocked) {
        alert('🔒 Невозможно удалить защищённую коллекцию.\n\nДля снятия защиты необходимо вручную изменить файл vector_databases.json (установить "locked": false).');
        return;
    }

    // Открываем модальное окно подтверждения
    pendingDeleteCollection = name;

    // Заполняем название коллекции в модалке
    els.deleteCollectionName.textContent = name;
    els.deleteCollectionNameHint.textContent = name;

    // Очищаем поле ввода и сбрасываем состояние
    els.deleteConfirmInput.value = '';
    els.deleteConfirmInput.classList.remove('valid', 'invalid');
    els.confirmDeleteBtn.disabled = true;

    // Показываем модальное окно
    els.modals.deleteConfirm.classList.add('active');
};

// Проверка ввода названия коллекции
els.deleteConfirmInput.addEventListener('input', () => {
    const inputValue = els.deleteConfirmInput.value.trim();
    const isValid = inputValue === pendingDeleteCollection;

    els.deleteConfirmInput.classList.toggle('valid', isValid);
    els.deleteConfirmInput.classList.toggle('invalid', inputValue.length > 0 && !isValid);
    els.confirmDeleteBtn.disabled = !isValid;
});

// Подтверждение удаления
els.confirmDeleteBtn.addEventListener('click', async () => {
    if (!pendingDeleteCollection) return;

    const inputValue = els.deleteConfirmInput.value.trim();
    if (inputValue !== pendingDeleteCollection) {
        alert('Название коллекции введено неверно!');
        return;
    }

    try {
        els.confirmDeleteBtn.disabled = true;
        els.confirmDeleteBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Удаление...';

        const res = await authFetch(`/admin/collections/${pendingDeleteCollection}`, { method: 'DELETE' });
        const result = await res.json();

        if (res.ok) {
            // Закрываем модалку
            els.modals.deleteConfirm.classList.remove('active');
            pendingDeleteCollection = null;

            // Показываем сообщение если требуется перезапуск
            if (result.pending_cleanup) {
                alert('✅ Коллекция удалена!\n\n⚠️ Папка с данными будет полностью очищена при следующем перезапуске сервера.');
            }

            // Обновляем список коллекций
            loadCollections();
        } else {
            alert('Ошибка удаления: ' + (result.detail || 'Неизвестная ошибка'));
        }
    } catch (e) {
        alert('Ошибка сети: ' + e.message);
    } finally {
        els.confirmDeleteBtn.disabled = false;
        els.confirmDeleteBtn.innerHTML = '<i class="fas fa-trash"></i> Удалить навсегда';
    }
});

// === CREATE COLLECTION ===
function initCreateCollection() {
    els.createCollBtn.addEventListener('click', async () => {
        const id = els.newCollId.value.trim();
        const name = els.newCollName.value.trim();
        const cosine = parseFloat(els.newCollCosine.value);
        const rerank = parseFloat(els.newCollRerank.value);
        const visible = els.newCollVisible.checked;

        if (!id) return alert('ID коллекции обязателен');

        try {
            // === ОПРЕДЕЛЯЕМ РАЗМЕРНОСТЬ НА ОСНОВЕ ТЕКУЩЕГО ПРОВАЙДЕРА ===
            // Получаем размерность эмбеддингов с сервера (зависит от OpenRouter/локальной модели)
            let dimension = 1024;  // Fallback для локальной модели
            try {
                const dimRes = await authFetch('/admin/embedding_dimension');
                if (dimRes.ok) {
                    const dimData = await dimRes.json();
                    dimension = dimData.dimension;
                    console.log(`📐 Размерность эмбеддингов: ${dimension} (${dimData.provider}: ${dimData.model})`);
                } else {
                    console.warn('Не удалось получить размерность — используем 1024');
                }
            } catch (e) {
                console.warn('Ошибка определения размерности:', e);
            }

            const res1 = await fetch('/create_collection', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    collection_name: id,
                    description: name,
                    dimension: dimension,  // Динамическая размерность!
                    recreate: false
                })
            });

            if (!res1.ok) {
                const err = await res1.json();
                throw new Error(err.detail || 'Не удалось создать коллекцию');
            }

            const res2 = await authFetch(`/admin/collections/${id}/config`, {
                method: 'POST',
                body: JSON.stringify({
                    visible: visible,
                    locked: false,
                    thresholds: { cosine, rerank },
                    dimension: dimension  // Сохраняем размерность в конфиг
                })
            });

            if (!res2.ok) console.warn('Создано, но не удалось обновить конфиг');

            closeModal('create');
            loadCollections();

        } catch (e) {
            alert('Ошибка: ' + e.message);
        }
    });
}

// === CONFIG MODAL ===
window.openConfig = (name) => {
    const c = state.collections.find(x => x.name === name);
    if (!c) return;

    els.cfgName.value = c.name;
    els.cfgCosine.value = c.thresholds?.cosine ?? 0.45;
    els.cfgRerank.value = c.thresholds?.rerank ?? 0.6;
    els.cfgVisible.checked = c.visible !== undefined ? c.visible : true;

    openModal('config');
};

els.saveConfigBtn.addEventListener('click', async () => {
    const name = els.cfgName.value;
    const body = {
        visible: els.cfgVisible.checked,
        locked: false,
        thresholds: {
            cosine: parseFloat(els.cfgCosine.value),
            rerank: parseFloat(els.cfgRerank.value)
        }
    };

    try {
        await authFetch(`/admin/collections/${name}/config`, {
            method: 'POST',
            body: JSON.stringify(body)
        });

        closeModal('config');
        loadCollections();
    } catch (e) {
        if (e.message !== 'Unauthorized') {
            alert('Ошибка сохранения настроек');
        }
    }
});

// === DATA VIEW ===
window.openDataView = (name) => {
    state.activeCollection = name;
    switchView('data');
    state.dataOffset = null;
    state.dataRows = [];
    state.sortColumn = null;
    state.sortDirection = 'asc';
    state.pathLevelColumns = []; // Сброс колонок иерархии
    els.dataTableBody.innerHTML = '';
    updateSortIcons();
    loadData();
};

async function loadData() {
    // Защита от повторных вызовов при infinite scroll
    if (!state.activeCollection || state.isLoadingData) return;

    state.isLoadingData = true;
    showInfiniteScrollLoader(true);

    try {
        const offsetQuery = state.dataOffset ? `&offset=${state.dataOffset}` : '';
        // Увеличим limit для более плавной прокрутки
        const res = await authFetch(`/admin/collections/${state.activeCollection}/data?limit=100${offsetQuery}`);
        const result = await res.json();

        state.dataOffset = result.next_offset;

        if (result.data.length === 0 && state.dataRows.length === 0) {
            els.dataTableBody.innerHTML = '<tr><td colspan="10" style="text-align:center; padding:30px; color:var(--adm-text-sec)">Записей не найдено. Добавьте новые!</td></tr>';
        } else {
            // Добавляем к существующим данным
            state.dataRows = state.dataRows.concat(result.data);

            // === ИСПРАВЛЕНО: Используем max_path_depth из ответа сервера ===
            // Это гарантирует корректное отображение ВСЕХ уровней категорий,
            // даже если первая запись имеет меньше уровней чем другие записи.
            if (result.data.length > 0 && state.pathLevelColumns.length === 0) {
                // Передаём max_path_depth из ответа сервера (вычисленный по ВСЕМ записям)
                const serverMaxDepth = result.max_path_depth || 0;
                extractPathLevelColumns(result.data[0], serverMaxDepth);
            }

            renderDataTable();
        }

        // Если есть ещё данные - продолжаем наблюдение, иначе останавливаем
        if (!state.dataOffset) {
            stopInfiniteScroll();
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') {
            console.error('Failed to load data:', e);
        }
    } finally {
        state.isLoadingData = false;
        showInfiniteScrollLoader(false);
    }
}

/**
 * Показать/скрыть индикатор загрузки для infinite scroll
 * @param {boolean} show - Показать или скрыть
 */
function showInfiniteScrollLoader(show) {
    const loader = document.getElementById('infiniteScrollLoader');
    if (loader) {
        loader.classList.toggle('hidden', !show);
    }
}

/**
 * Инициализация infinite scroll с IntersectionObserver
 */
function initInfiniteScroll() {
    // Останавливаем предыдущий observer если есть
    stopInfiniteScroll();

    const sentinel = document.getElementById('scrollSentinel');
    if (!sentinel) return;

    // Создаём IntersectionObserver
    state.scrollObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            // Когда sentinel становится видимым - загружаем ещё данные
            if (entry.isIntersecting && state.dataOffset && !state.isLoadingData) {
                loadData();
            }
        });
    }, {
        root: document.querySelector('.data-table-scroll'),
        rootMargin: '100px', // Начинаем загрузку за 100px до конца
        threshold: 0
    });

    state.scrollObserver.observe(sentinel);
}

/**
 * Остановка infinite scroll
 */
function stopInfiniteScroll() {
    if (state.scrollObserver) {
        state.scrollObserver.disconnect();
        state.scrollObserver = null;
    }
}

// === COLUMN RESIZE ===
/**
 * Инициализация drag-resize для колонок таблицы.
 * Позволяет изменять ширину колонок как в Excel/Google Sheets.
 * 
 * УЛУЧШЕНИЯ v2:
 * - Визуальная ручка resize с 3 точками
 * - Линия-индикатор при перетаскивании
 * - Увеличенная область активации (12px вместо 5px)
 * - Не конфликтует с сортировкой (отдельные области)
 */
function initColumnResize() {
    const table = document.getElementById('dataTable');
    if (!table) return;

    const headerCells = table.querySelectorAll('thead th');

    // Создаём линию-индикатор (один раз для всей таблицы)
    let resizeLine = document.querySelector('.resize-line');
    if (!resizeLine) {
        resizeLine = document.createElement('div');
        resizeLine.className = 'resize-line';
        document.body.appendChild(resizeLine);
    }

    headerCells.forEach((th, index) => {
        // Не добавляем resizer для последней колонки (Действия)
        if (index === headerCells.length - 1) return;

        // Проверяем, есть ли уже resizer (избегаем дублирования)
        if (th.querySelector('.th-resizer')) return;

        // Создаём элемент resizer
        const resizer = document.createElement('div');
        resizer.className = 'th-resizer';
        th.appendChild(resizer);

        // Восстанавливаем сохранённую ширину
        const columnKey = th.dataset.sort || `col_${index}`;
        if (state.columnWidths[columnKey]) {
            th.style.width = state.columnWidths[columnKey] + 'px';
            th.style.minWidth = state.columnWidths[columnKey] + 'px';
        }

        // Обработчики событий для resize
        let startX, startWidth;

        resizer.addEventListener('mousedown', (e) => {
            e.preventDefault();
            e.stopPropagation();

            startX = e.pageX;
            startWidth = th.offsetWidth;

            // Показываем линию-индикатор
            const thRect = th.getBoundingClientRect();
            resizeLine.style.left = (thRect.right - 1) + 'px';
            resizeLine.classList.add('visible');

            resizer.classList.add('active');
            document.body.classList.add('resizing-columns');

            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });

        function onMouseMove(e) {
            const diff = e.pageX - startX;
            const newWidth = Math.max(60, startWidth + diff); // Минимум 60px

            // Обновляем ширину столбца
            th.style.width = newWidth + 'px';
            th.style.minWidth = newWidth + 'px';

            // Обновляем позицию линии-индикатора
            const thRect = th.getBoundingClientRect();
            resizeLine.style.left = (thRect.right - 1) + 'px';
        }

        function onMouseUp() {
            // Скрываем линию-индикатор
            resizeLine.classList.remove('visible');

            resizer.classList.remove('active');
            document.body.classList.remove('resizing-columns');

            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);

            // Сохраняем ширину в localStorage
            const columnKey = th.dataset.sort || `col_${index}`;
            state.columnWidths[columnKey] = th.offsetWidth;
            localStorage.setItem('adminColumnWidths', JSON.stringify(state.columnWidths));
        }
    });
}

/**
 * Извлечение колонок path_level_N из данных записи.
 * 
 * ИСПРАВЛЕНО: Теперь использует serverMaxDepth (максимальная глубина по ВСЕЙ коллекции),
 * вычисленную на сервере. Это гарантирует отображение ВСЕХ уровней категорий,
 * даже если первая запись имеет меньше уровней.
 * 
 * @param {Object} row - Запись с данными (для проверки наличия full_description)
 * @param {number} serverMaxDepth - Максимальная глубина иерархии, вычисленная сервером
 */
function extractPathLevelColumns(row, serverMaxDepth = 0) {
    const meta = row.meta || {};
    const pathLevels = [];

    // === ИСПРАВЛЕНО: Приоритет использования serverMaxDepth ===
    // serverMaxDepth вычислен по ВСЕМ записям коллекции на сервере
    // Это решает проблему когда первая запись имеет меньше уровней чем остальные
    let pathDepth = serverMaxDepth;

    // Fallback на path_depth из первой записи если сервер вернул 0
    if (pathDepth === 0) {
        pathDepth = meta.path_depth || 0;
    }

    if (pathDepth > 0) {
        // Используем pathDepth для определения количества уровней
        for (let i = 1; i <= pathDepth; i++) {
            pathLevels.push({
                key: `path_level_${i}`,
                level: i
            });
        }
    } else {
        // Fallback: ищем все path_level_N в данных первой записи
        Object.keys(meta).forEach(key => {
            const match = key.match(/^path_level_(\d+)$/);
            if (match) {
                pathLevels.push({
                    key: key,
                    level: parseInt(match[1])
                });
            }
        });
        // Сортируем по номеру уровня
        pathLevels.sort((a, b) => a.level - b.level);
    }

    state.pathLevelColumns = pathLevels;

    // Проверяем наличие full_description
    state.hasFullDescription = 'full_description' in meta;

    console.log(`📊 Найдено ${pathLevels.length} уровней иерархии (serverMaxDepth: ${serverMaxDepth}), full_description: ${state.hasFullDescription}`);
}

function renderDataTable() {
    // Генерируем заголовок таблицы с динамическими колонками иерархии
    renderDataTableHeader();

    els.dataTableBody.innerHTML = '';

    // Применяем сортировку если задана
    let sortedRows = [...state.dataRows];
    if (state.sortColumn) {
        sortedRows.sort((a, b) => {
            let valA, valB;

            // Определяем откуда брать значение для сортировки
            if (state.sortColumn === 'code') {
                valA = a.code || '';
                valB = b.code || '';
            } else if (state.sortColumn === 'full_description') {
                // Полное описание материала - из meta или fallback на description
                valA = (a.meta && a.meta.full_description) || a.description || '';
                valB = (b.meta && b.meta.full_description) || b.description || '';
            } else if (state.sortColumn.startsWith('path_level_')) {
                // Уровни категорий - из meta
                valA = (a.meta && a.meta[state.sortColumn]) || '';
                valB = (b.meta && b.meta[state.sortColumn]) || '';
            } else if (state.sortColumn === 'updated_at') {
                // Дата изменения - сортировка по ISO строке
                valA = (a.meta && a.meta.updated_at) || '';
                valB = (b.meta && b.meta.updated_at) || '';
            } else if (state.sortColumn === 'version') {
                // Версия - числовая сортировка
                valA = (a.meta && a.meta.version) || 1;
                valB = (b.meta && b.meta.version) || 1;
                // Для числовой сортировки
                if (valA < valB) return state.sortDirection === 'asc' ? -1 : 1;
                if (valA > valB) return state.sortDirection === 'asc' ? 1 : -1;
                return 0;
            } else {
                // Любое другое поле
                valA = a[state.sortColumn] || '';
                valB = b[state.sortColumn] || '';
            }

            valA = valA.toString().toLowerCase();
            valB = valB.toString().toLowerCase();

            if (valA < valB) return state.sortDirection === 'asc' ? -1 : 1;
            if (valA > valB) return state.sortDirection === 'asc' ? 1 : -1;
            return 0;
        });
    }

    sortedRows.forEach(row => {
        renderRow(row);
    });

    initInlineEdit();

    // Инициализируем infinite scroll после рендера таблицы
    initInfiniteScroll();
}

/**
 * Генерация заголовка таблицы с динамическими колонками иерархии.
 * 
 * НОВАЯ ЛОГИКА v4:
 * - Код (сортируемый, по центру)
 * - Уровни категорий (path_level_N) - все сортируемые
 * - Полное описание материала (full_description) - сортируемый
 * - Дата изменения (updated_at) - сортируемая
 * - Версия (version)
 * - Статус (status) - фильтруемый
 * - Действия (по центру)
 * 
 * УЛУЧШЕНИЕ: Название столбца обёрнуто в .sort-trigger для отделения
 * области сортировки от области изменения ширины (resize).
 * Сортировка срабатывает ТОЛЬКО при клике на название, не на всю колонку.
 */
function renderDataTableHeader() {
    const thead = document.getElementById('dataTableHead');
    if (!thead) return;

    let html = '<tr>';

    /**
     * Вспомогательная функция для создания заголовка с сортировкой.
     * Название обёрнуто в .sort-trigger для отделения от resize.
     */
    const createSortableHeader = (sortKey, label, iconClass, isCenter = false, extraClass = '') => {
        const isActive = state.sortColumn === sortKey;
        const sortIcon = isActive ? (state.sortDirection === 'asc' ? 'fa-sort-up' : 'fa-sort-down') : 'fa-sort';
        const centerStyle = isCenter ? 'text-align: center;' : '';
        const iconHtml = iconClass ? `<i class="fas ${iconClass}" style="opacity: 0.6; margin-right: 5px;"></i>` : '';

        return `
            <th class="sortable ${extraClass}" data-sort="${sortKey}" style="min-width: 120px; ${centerStyle}">
                <div class="th-content">
                    <span class="sort-trigger" data-sort="${sortKey}">
                        ${iconHtml}${label}
                        <i class="fas ${sortIcon} sort-icon${isActive ? ' active' : ''}"></i>
                    </span>
                </div>
            </th>
        `;
    };

    // Колонка Код (сортируемая, по центру)
    html += createSortableHeader('code', 'Код', null, true);

    // Динамические колонки иерархии (все сортируемые)
    state.pathLevelColumns.forEach((col) => {
        const isActive = state.sortColumn === col.key;
        const sortIcon = isActive ? (state.sortDirection === 'asc' ? 'fa-sort-up' : 'fa-sort-down') : 'fa-sort';
        html += `
            <th class="sortable col-hierarchy-header" data-sort="${col.key}" style="min-width: 120px;">
                <div class="th-content">
                    <span class="sort-trigger" data-sort="${col.key}">
                        <i class="fas fa-folder" style="color: #f59e0b; margin-right: 5px;"></i>
                        Уровень ${col.level}
                        <i class="fas ${sortIcon} sort-icon${isActive ? ' active' : ''}"></i>
                    </span>
                </div>
            </th>
        `;
    });

    // Колонка Полное описание материала (full_description)
    const descActive = state.sortColumn === 'full_description';
    const descIcon = descActive ? (state.sortDirection === 'asc' ? 'fa-sort-up' : 'fa-sort-down') : 'fa-sort';
    html += `
        <th class="sortable" data-sort="full_description" style="min-width: 300px;">
            <div class="th-content">
                <span class="sort-trigger" data-sort="full_description">
                    Полное описание
                    <i class="fas ${descIcon} sort-icon${descActive ? ' active' : ''}"></i>
                </span>
            </div>
        </th>
    `;

    // Колонка Дата изменения (сортируемая)
    html += createSortableHeader('updated_at', 'Изменено', 'fa-clock', true);

    // Колонка Версия (не сортируемая)
    html += `
        <th style="min-width: 70px; text-align: center;">
            <div class="th-content" style="justify-content: center;">
                <i class="fas fa-code-branch" style="margin-right: 5px; opacity: 0.6;"></i>
                Версия
            </div>
        </th>
    `;

    // Колонка Статус (не сортируемая)
    html += `
        <th style="min-width: 130px; text-align: center;">
            <div class="th-content" style="justify-content: center;">
                <i class="fas fa-tag" style="margin-right: 5px; opacity: 0.6;"></i>
                Статус
            </div>
        </th>
    `;

    // Колонка Действия (по центру, без resize)
    html += '<th class="col-actions-header" style="width: 80px; text-align: center;">Действия</th>';

    html += '</tr>';
    thead.innerHTML = html;

    // Перепривязываем обработчики сортировки и resize
    initSorting();
    initColumnResize();
}

/**
 * Рендеринг строки таблицы данных.
 * 
 * НОВАЯ ЛОГИКА v3:
 * - Код (редактируемый, по центру)
 * - Уровни категорий (path_level_N) - редактируемые, показывают ТОЛЬКО своё значение
 * - Полное описание материала (full_description) - редактируемое
 * - Дата изменения (updated_at) - только чтение
 * - Версия (version) - только чтение
 * - Статус (status) - редактируемый через select
 * - Действия (по центру)
 * 
 * @param {Object} row - Запись с данными {id, code, description, meta}
 */
function renderRow(row) {
    const tr = document.createElement('tr');
    tr.dataset.rowId = row.id;

    const meta = row.meta || {};

    // Колонка Код (редактируемая, по центру)
    let html = `<td class="col-code editable" data-id="${row.id}" data-field="code">${escapeHtml(row.code || '')}</td>`;

    // Динамические колонки иерархии (редактируемые)
    // НОВАЯ ЛОГИКА: Показываем ТОЛЬКО значение текущего уровня, без контекста предыдущих
    state.pathLevelColumns.forEach(col => {
        const value = meta[col.key] || '';
        html += `<td class="col-hierarchy editable" data-id="${row.id}" data-field="${col.key}" title="${escapeHtml(value)}">${escapeHtml(value)}</td>`;
    });

    // Колонка Полное описание материала (full_description)
    // Если есть full_description - используем его, иначе fallback на description
    const fullDescription = meta.full_description || row.description || '';
    html += `<td class="col-description editable" data-id="${row.id}" data-field="full_description">${escapeHtml(fullDescription)}</td>`;

    // Колонка Дата изменения (только чтение)
    const updatedAt = meta.updated_at ? formatDateTime(meta.updated_at) : '—';
    html += `<td class="col-date">${updatedAt}</td>`;

    // Колонка Версия (только чтение)
    const version = meta.version || 1;
    html += `<td class="col-version"><span class="version-badge">v${version}</span></td>`;

    // Колонка Статус (редактируемый через select)
    const currentStatus = meta.status || state.defaultStatus;
    html += `<td class="col-status">${renderStatusSelect(row.id, currentStatus)}</td>`;

    // Колонка Действия (по центру)
    html += `
        <td class="col-actions">
            <button class="btn btn-danger btn-delete-record" style="padding: 6px;" data-id="${row.id}">
                <i class="fas fa-trash"></i>
            </button>
        </td>
    `;

    tr.innerHTML = html;
    els.dataTableBody.appendChild(tr);

    // Обработчики для dropdown статусов привязываются через делегирование
    // в функции initStatusDropdowns() - один раз на документ
}

/**
 * Форматирование даты/времени для отображения
 * @param {string} isoString - ISO строка даты
 * @returns {string} Отформатированная дата
 */
function formatDateTime(isoString) {
    if (!isoString) return '—';
    try {
        const date = new Date(isoString);
        const day = String(date.getDate()).padStart(2, '0');
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const year = date.getFullYear();
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        return `${day}.${month}.${year} ${hours}:${minutes}`;
    } catch {
        return '—';
    }
}

/**
 * Рендеринг кастомного выпадающего списка статусов.
 * 
 * УЛУЧШЕНИЯ v2:
 * - Кастомный dropdown вместо нативного select
 * - Цветные точки рядом со статусами
 * - Плавная анимация открытия/закрытия
 * - Галочка у выбранного элемента
 * 
 * @param {string} recordId - ID записи
 * @param {string} currentStatus - Текущий статус
 * @returns {string} HTML кастомного dropdown
 */
function renderStatusSelect(recordId, currentStatus) {
    // Находим текущий статус
    const currentStatusObj = state.statuses.find(s => s.id === currentStatus);
    const statusColor = currentStatusObj ? currentStatusObj.color : '#64748b';
    const statusLabel = currentStatusObj ? currentStatusObj.label : currentStatus;

    // Генерируем опции
    let optionsHtml = '';
    state.statuses.forEach(status => {
        const isSelected = status.id === currentStatus;
        optionsHtml += `
            <div class="status-option ${isSelected ? 'selected' : ''}" data-value="${status.id}">
                <span class="status-dot" style="background: ${status.color};"></span>
                <span class="status-label">${status.label}</span>
                <i class="fas fa-check status-check"></i>
            </div>
        `;
    });

    // Если статусы ещё не загружены - показываем текущий
    if (state.statuses.length === 0) {
        optionsHtml = `
            <div class="status-option selected" data-value="${currentStatus}">
                <span class="status-dot" style="background: #64748b;"></span>
                <span class="status-label">${currentStatus}</span>
                <i class="fas fa-check status-check"></i>
            </div>
        `;
    }

    return `
        <div class="status-dropdown" data-id="${recordId}">
            <div class="status-dropdown-trigger" tabindex="0">
                <span class="status-dot" style="background: ${statusColor};"></span>
                <span class="status-label">${statusLabel}</span>
                <i class="fas fa-chevron-down status-arrow"></i>
            </div>
            <div class="status-dropdown-options">
                ${optionsHtml}
            </div>
        </div>
    `;
}

/**
 * Инициализация кастомных dropdown статусов.
 * Привязывает обработчики событий к dropdown элементам.
 */
function initStatusDropdowns() {
    // Закрытие всех dropdown при клике вне
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.status-dropdown')) {
            document.querySelectorAll('.status-dropdown.open').forEach(dd => {
                dd.classList.remove('open');
            });
        }
    });

    // Делегирование событий для trigger
    document.addEventListener('click', (e) => {
        const trigger = e.target.closest('.status-dropdown-trigger');
        if (!trigger) return;

        const dropdown = trigger.closest('.status-dropdown');
        const wasOpen = dropdown.classList.contains('open');

        // Закрываем все остальные
        document.querySelectorAll('.status-dropdown.open').forEach(dd => {
            if (dd !== dropdown) dd.classList.remove('open');
        });

        // Переключаем текущий
        dropdown.classList.toggle('open', !wasOpen);
    });

    // Делегирование событий для option
    document.addEventListener('click', (e) => {
        const option = e.target.closest('.status-option');
        if (!option) return;

        const dropdown = option.closest('.status-dropdown');
        const recordId = dropdown.dataset.id;
        const newStatus = option.dataset.value;

        // Закрываем dropdown
        dropdown.classList.remove('open');

        // Обновляем trigger
        const trigger = dropdown.querySelector('.status-dropdown-trigger');
        const statusObj = state.statuses.find(s => s.id === newStatus);

        if (statusObj && trigger) {
            trigger.querySelector('.status-dot').style.background = statusObj.color;
            trigger.querySelector('.status-label').textContent = statusObj.label;
        }

        // Обновляем selected состояние
        dropdown.querySelectorAll('.status-option').forEach(opt => {
            opt.classList.toggle('selected', opt.dataset.value === newStatus);
        });

        // Вызываем обработчик изменения статуса
        handleStatusChange(recordId, newStatus);
    });
}

/**
 * Обработчик изменения статуса записи
 * @param {string} recordId - ID записи
 * @param {string} newStatus - Новый статус
 */
async function handleStatusChange(recordId, newStatus) {
    try {
        const res = await authFetch(`/admin/collections/${state.activeCollection}/data/${recordId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ field: 'status', value: newStatus })
        });

        if (!res.ok) {
            throw new Error('Failed to update status');
        }

        const result = await res.json();

        // === ИСПРАВЛЕНО: Поиск по ID с приведением типов ===
        const rowData = state.dataRows.find(r => String(r.id) === String(recordId));
        if (rowData) {
            if (!rowData.meta) rowData.meta = {};
            rowData.meta.status = newStatus;

            // === НОВОЕ: Обновляем дату и версию из ответа сервера ===
            if (result.updated_at) {
                rowData.meta.updated_at = result.updated_at;
                rowData.meta.version = result.version;
                updateRowMetaDisplay(recordId, result.updated_at, result.version);
            }
        }

        // Визуальное подтверждение (кастомный dropdown уже обновлён в initStatusDropdowns)
        console.log(`✅ Статус записи ${recordId} изменён на ${newStatus}`);

    } catch (e) {
        console.error('Ошибка изменения статуса:', e);
        alert('Не удалось изменить статус');

        // Откатываем dropdown на предыдущее значение
        const rowData = state.dataRows.find(r => String(r.id) === String(recordId));
        if (rowData) {
            const dropdown = document.querySelector(`.status-dropdown[data-id="${recordId}"]`);
            if (dropdown) {
                const previousStatus = rowData.meta?.status || state.defaultStatus;
                const statusObj = state.statuses.find(s => s.id === previousStatus);

                // Восстанавливаем trigger
                const trigger = dropdown.querySelector('.status-dropdown-trigger');
                if (trigger && statusObj) {
                    trigger.querySelector('.status-dot').style.background = statusObj.color;
                    trigger.querySelector('.status-label').textContent = statusObj.label;
                }

                // Восстанавливаем selected состояние
                dropdown.querySelectorAll('.status-option').forEach(opt => {
                    opt.classList.toggle('selected', opt.dataset.value === previousStatus);
                });
            }
        }
    }
}

// === SORTING ===
/**
 * Инициализация сортировки таблицы.
 * 
 * УЛУЧШЕНИЕ: Обработчик привязывается к .sort-trigger внутри th,
 * а не ко всему th. Это позволяет отделить область сортировки
 * от области изменения ширины столбца (resize).
 */
function initSorting() {
    // Привязываем обработчик к .sort-trigger, а не ко всему th
    document.querySelectorAll('.sort-trigger').forEach(trigger => {
        // Убираем старые обработчики (если есть)
        trigger.replaceWith(trigger.cloneNode(true));
    });

    // Заново привязываем обработчики к свежим элементам
    document.querySelectorAll('.sort-trigger').forEach(trigger => {
        trigger.addEventListener('click', (e) => {
            e.stopPropagation(); // Не даём событию всплыть к th

            const column = trigger.dataset.sort;
            if (!column) return;

            if (state.sortColumn === column) {
                // Переключаем направление
                state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                state.sortColumn = column;
                state.sortDirection = 'asc';
            }

            updateSortIcons();
            renderDataTable();
        });
    });
}

/**
 * Обновление иконок сортировки в заголовках таблицы.
 */
function updateSortIcons() {
    document.querySelectorAll('th.sortable').forEach(th => {
        const icon = th.querySelector('.sort-icon');
        const column = th.dataset.sort;

        if (icon) {
            if (state.sortColumn === column) {
                icon.className = `fas fa-sort-${state.sortDirection === 'asc' ? 'up' : 'down'} sort-icon active`;
            } else {
                icon.className = 'fas fa-sort sort-icon';
            }
        }
    });
}

// loadMoreBtn заменён на infinite scroll - см. initInfiniteScroll()
// els.loadMoreBtn.addEventListener('click', loadData);

// === ADD RECORD ===
function initAddRecord() {
    els.saveRecBtn.addEventListener('click', async () => {
        const code = els.newRecCode.value.trim();
        const desc = els.newRecDesc.value.trim();

        if (!code || !desc) return alert('Оба поля обязательны');

        try {
            const res = await fetch('/update_record', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    code: code,
                    description: desc,
                    database: state.activeCollection
                })
            });

            if (res.ok) {
                // Инвалидируем кэш иерархии для обновления каталога
                try {
                    await fetch(`/hierarchy/${state.activeCollection}/invalidate`, { method: 'POST' });
                    console.log('✅ Кэш иерархии очищен после добавления записи');
                } catch (e) {
                    console.warn('⚠️ Не удалось очистить кэш иерархии:', e);
                }

                closeModal('addRecord');
                state.dataOffset = null;
                state.dataRows = [];
                els.dataTableBody.innerHTML = '';
                loadData();
            } else {
                const err = await res.json();
                alert('Ошибка: ' + (err.detail || 'Не удалось сохранить'));
            }
        } catch (e) {
            alert('Ошибка: ' + e);
        }
    });
}

// === EDIT RECORD (INLINE) ===
/**
 * Инициализация inline-редактирования ячеек таблицы.
 * 
 * НОВАЯ ЛОГИКА v2:
 * - Поддержка редактирования code, path_level_N, full_description
 * - При изменении path_level_N или full_description сервер пересчитывает эмбеддинги
 * - Показываем уведомление о пересчёте эмбеддингов
 */
function initInlineEdit() {
    document.querySelectorAll('.editable').forEach(td => {
        if (td.dataset.bound) return;
        td.dataset.bound = true;

        td.addEventListener('dblclick', function () {
            if (this.classList.contains('editing')) return;

            const originalVal = this.innerText;
            const id = this.dataset.id;
            const field = this.dataset.field;

            this.classList.add('editing');

            const input = document.createElement('input');
            input.type = 'text';
            input.value = originalVal;

            this.innerHTML = '';
            this.appendChild(input);
            input.focus();

            const cellElement = this;

            const save = async () => {
                const newVal = input.value;
                if (newVal === originalVal) {
                    cellElement.innerHTML = originalVal;
                    cellElement.classList.remove('editing');
                    return;
                }

                // Показываем индикатор загрузки для полей, требующих пересчёт эмбеддингов
                const needsReembed = field === 'full_description' ||
                    field === 'description' ||
                    field.startsWith('path_level_');

                if (needsReembed) {
                    cellElement.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Пересчёт...';
                }

                try {
                    const res = await authFetch(`/admin/collections/${state.activeCollection}/data/${id}`, {
                        method: 'POST',
                        body: JSON.stringify({
                            code: field === 'code' ? newVal : '',
                            field: field,
                            value: newVal
                        })
                    });

                    if (res.ok) {
                        const result = await res.json();
                        cellElement.innerHTML = escapeHtml(newVal);

                        // === ИСПРАВЛЕНО: Поиск по ID с приведением типов ===
                        // ID может быть строкой или числом, приводим к строке для сравнения
                        const row = state.dataRows.find(r => String(r.id) === String(id));

                        if (row) {
                            if (field === 'code') {
                                row.code = newVal;
                            } else if (field === 'full_description') {
                                // Обновляем full_description в meta
                                if (!row.meta) row.meta = {};
                                row.meta.full_description = newVal;
                                row.meta.context_description = result.context_description;
                                row.description = result.context_description;
                            } else if (field.startsWith('path_level_')) {
                                // Обновляем уровень категории в meta
                                if (!row.meta) row.meta = {};
                                row.meta[field] = newVal;
                                row.meta.context_description = result.context_description;
                                row.description = result.context_description;
                            } else if (field === 'description') {
                                row.description = newVal;
                            }

                            // === НОВОЕ: Обновляем дату и версию из ответа сервера ===
                            if (result.updated_at) {
                                if (!row.meta) row.meta = {};
                                row.meta.updated_at = result.updated_at;
                                row.meta.version = result.version;

                                // Обновляем отображение в DOM для этой конкретной строки
                                updateRowMetaDisplay(id, result.updated_at, result.version);
                            }
                        }

                        // Показываем уведомление если был пересчёт
                        if (needsReembed && result.context_description) {
                            console.log(`✅ Эмбеддинг пересчитан для: ${result.context_description.substring(0, 50)}...`);
                        }
                    } else {
                        const err = await res.json();
                        alert('Ошибка обновления: ' + (err.detail || 'Неизвестная ошибка'));
                        cellElement.innerHTML = escapeHtml(originalVal);
                    }
                } catch (e) {
                    if (e.message !== 'Unauthorized') {
                        alert('Ошибка обновления: ' + e.message);
                        cellElement.innerHTML = escapeHtml(originalVal);
                    }
                } finally {
                    cellElement.classList.remove('editing');
                }
            };

            input.addEventListener('blur', save);
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') input.blur();
                if (e.key === 'Escape') {
                    cellElement.innerHTML = escapeHtml(originalVal);
                    cellElement.classList.remove('editing');
                }
            });
        });
    });
}

/**
 * Обновление отображения даты и версии в конкретной строке таблицы.
 * Находит строку по ID и обновляет соответствующие ячейки.
 * 
 * @param {string} recordId - ID записи
 * @param {string} updatedAt - Новая дата изменения (ISO формат)
 * @param {number} version - Новая версия
 */
function updateRowMetaDisplay(recordId, updatedAt, version) {
    // Находим строку таблицы по data-row-id
    const row = document.querySelector(`tr[data-row-id="${recordId}"]`);
    if (!row) {
        console.warn(`⚠️ Строка с ID ${recordId} не найдена в DOM`);
        return;
    }

    // Обновляем ячейку с датой
    const dateCell = row.querySelector('.col-date');
    if (dateCell) {
        dateCell.textContent = formatDateTime(updatedAt);
    }

    // Обновляем ячейку с версией
    const versionCell = row.querySelector('.col-version');
    if (versionCell) {
        versionCell.innerHTML = `<span class="version-badge">v${version}</span>`;
    }

    console.log(`✅ Обновлено отображение: ID=${recordId}, дата=${formatDateTime(updatedAt)}, версия=v${version}`);
}

/**
 * Удаление записи из коллекции.
 * Проверяет блокировку коллекции перед удалением.
 * 
 * ИСПРАВЛЕНО: Теперь корректно обрабатывает ответ сервера и удаляет запись из UI.
 * 
 * @param {string} id - ID записи (UUID из Qdrant)
 */
window.deleteRecord = async (id) => {
    // Проверяем блокировку коллекции
    const collection = state.collections.find(c => c.name === state.activeCollection);
    if (collection && collection.locked) {
        alert('🔒 Невозможно удалить запись - коллекция защищена.\n\nДля снятия защиты измените locked: false в настройках.');
        return;
    }

    if (!confirm('Вы уверены, что хотите удалить эту запись?')) return;

    try {
        console.log(`🗑️ Удаление записи с ID: ${id} из коллекции ${state.activeCollection}`);

        const res = await authFetch(`/admin/collections/${state.activeCollection}/data/${id}`, {
            method: 'DELETE'
        });

        // Проверяем успешность ответа
        if (!res.ok) {
            const errorData = await res.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP ${res.status}`);
        }

        console.log(`✅ Запись ${id} успешно удалена на сервере`);

        // Инвалидируем кэш иерархии для обновления каталога
        try {
            await fetch(`/hierarchy/${state.activeCollection}/invalidate`, { method: 'POST' });
            console.log('✅ Кэш иерархии очищен после удаления записи');
        } catch (e) {
            console.warn('⚠️ Не удалось очистить кэш иерархии:', e);
        }

        // Удаляем из state (приводим ID к строке для корректного сравнения)
        const beforeCount = state.dataRows.length;
        state.dataRows = state.dataRows.filter(r => String(r.id) !== String(id));
        const afterCount = state.dataRows.length;

        console.log(`📊 state.dataRows: ${beforeCount} → ${afterCount}`);

        // Удаляем из DOM
        const tr = document.querySelector(`tr[data-row-id="${id}"]`);
        if (tr) {
            tr.remove();
            console.log(`🗑️ Строка удалена из DOM`);
        } else {
            console.warn(`⚠️ Строка с data-row-id="${id}" не найдена в DOM`);
            // Перезагружаем данные если строка не найдена в DOM
            state.dataOffset = null;
            state.dataRows = [];
            els.dataTableBody.innerHTML = '';
            loadData();
        }

    } catch (e) {
        if (e.message !== 'Unauthorized') {
            console.error('❌ Ошибка удаления записи:', e);
            alert('Ошибка удаления: ' + e.message);
        }
    }
};

// Event delegation для кнопок удаления записей
document.addEventListener('click', (e) => {
    const deleteBtn = e.target.closest('.btn-delete-record');
    if (deleteBtn) {
        const id = deleteBtn.dataset.id;
        if (id) {
            deleteRecord(id);
        }
    }
});

// === IMPORT WIZARD ===

/**
 * Открытие модального окна импорта для коллекции.
 * Сбрасывает состояние визарда.
 */
window.openImport = (name) => {
    state.activeCollection = name;
    els.importTarget.value = name;

    // Сброс состояния
    els.pasteArea.value = '';
    state.importData = {
        raw: [],
        headers: [],
        codeSelection: {},
        descSelection: {},
        hierarchySelection: {},
        codeSeparator: '.',
        descSeparator: ' '  // По умолчанию пробел для описания
    };
    state.diffData = { added: [], modified: [], deleted: [], unchanged: 0, existingRecords: {} };
    state.diffActiveTab = 'added';

    // Сброс разделителей
    if (els.codeSeparator) els.codeSeparator.value = '.';
    if (els.descSeparator) els.descSeparator.value = ' ';

    // === Сброс UI загрузки Excel ===
    if (typeof resetExcelUploadUI === 'function') {
        resetExcelUploadUI();
    }

    // === Сброс вкладок на "Paste" ===
    const tabs = document.querySelectorAll('.source-tab');
    tabs.forEach(t => t.classList.remove('active'));
    const pasteTab = document.querySelector('.source-tab[data-source="paste"]');
    if (pasteTab) pasteTab.classList.add('active');

    document.querySelectorAll('.import-source-content').forEach(c => c.classList.remove('active'));
    const pasteContent = document.getElementById('importSourcePaste');
    if (pasteContent) pasteContent.classList.add('active');

    showImportStep('paste');
    openModal('import');
};

/**
 * Инициализация мастера импорта.
 * Настраивает обработчики событий для всех кнопок и элементов.
 */
function initImportWizard() {
    // Обработка вставки данных
    els.pasteArea.addEventListener('paste', (e) => {
        setTimeout(() => {
            const text = els.pasteArea.value.trim();
            if (text) processPastedData(text);
        }, 100);
    });

    // Кнопка "Далее" (шаг 1 → шаг 2)
    els.importBtns.next.addEventListener('click', () => {
        const text = els.pasteArea.value.trim();
        if (!text) return alert('Сначала вставьте данные.');
        processPastedData(text);
    });

    // Кнопка "Назад"
    els.importBtns.back.addEventListener('click', () => {
        // Определяем откуда вернуться
        if (els.importSteps.diff.classList.contains('active')) {
            showImportStep('mapping');
        } else if (els.importSteps.mapping.classList.contains('active')) {
            showImportStep('paste');
        }
    });

    // Кнопка "Сравнить с базой" (шаг 2 → diff)
    els.importBtns.compare.addEventListener('click', async () => {
        if (!validateMapping()) return;
        await performDiffAnalysis();
    });

    // Кнопка "Загрузить всё" (полная перезапись)
    els.importBtns.upload.addEventListener('click', async () => {
        if (!validateMapping()) return;
        await performFullUpload();
    });

    // Кнопка "Применить изменения" (точечное обновление)
    els.importBtns.apply.addEventListener('click', async () => {
        await applyDiffChanges();
    });

    // Обработчик изменения разделителя кода
    if (els.codeSeparator) {
        els.codeSeparator.addEventListener('input', () => {
            state.importData.codeSeparator = els.codeSeparator.value || '.';
            updateAllPreviews();
        });
    }

    // Обработчик изменения разделителя описания
    if (els.descSeparator) {
        els.descSeparator.addEventListener('input', () => {
            state.importData.descSeparator = els.descSeparator.value || ' ';
            updateAllPreviews();
        });
    }

    // === НОВОЕ: Инициализация вкладок источника импорта ===
    initImportSourceTabs();

    // === НОВОЕ: Инициализация загрузки Excel ===
    initExcelUpload();
}

/**
 * Инициализация переключения вкладок источника импорта (CSV/Excel).
 */
function initImportSourceTabs() {
    const tabs = document.querySelectorAll('.source-tab');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            // Снимаем активность со всех вкладок
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            // Переключаем контент
            const source = tab.dataset.source;
            document.querySelectorAll('.import-source-content').forEach(content => {
                content.classList.remove('active');
            });

            const targetContent = document.getElementById(
                source === 'paste' ? 'importSourcePaste' : 'importSourceExcel'
            );
            if (targetContent) {
                targetContent.classList.add('active');
            }
        });
    });
}

/**
 * Инициализация загрузки Excel файлов.
 */
function initExcelUpload() {
    const dropZone = document.getElementById('excelDropZone');
    const fileInput = document.getElementById('excelFileInput');
    const fileInfo = document.getElementById('excelFileInfo');
    const fileName = document.getElementById('excelFileName');
    const fileStats = document.getElementById('excelFileStats');
    const fileClear = document.getElementById('excelFileClear');
    const sheetSelector = document.getElementById('excelSheetSelector');
    const sheetSelect = document.getElementById('excelSheetSelect');

    if (!dropZone || !fileInput) return;

    // Drag and drop
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
        if (files.length > 0) {
            handleExcelFile(files[0]);
        }
    });

    // File input change
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleExcelFile(e.target.files[0]);
        }
    });

    // Clear file
    if (fileClear) {
        fileClear.addEventListener('click', () => {
            resetExcelUploadUI();
        });
    }

    // Sheet selection change
    if (sheetSelect) {
        sheetSelect.addEventListener('change', async () => {
            if (state.importData.excelFile) {
                await uploadExcelFile(state.importData.excelFile, sheetSelect.value);
            }
        });
    }
}

/**
 * Сброс интерфейса загрузки Excel в исходное состояние.
 * Восстанавливает HTML dropzone (удаляет спиннер) и скрывает инфо о файле.
 */
function resetExcelUploadUI() {
    const dropZone = document.getElementById('excelDropZone');
    const fileInput = document.getElementById('excelFileInput'); // Это старый input (если есть)
    const fileInfo = document.getElementById('excelFileInfo');
    const sheetSelector = document.getElementById('excelSheetSelector');

    // Очищаем значение, если input ещё существует
    if (fileInput) fileInput.value = '';

    // Скрываем панели
    if (fileInfo) fileInfo.classList.add('hidden');
    if (sheetSelector) sheetSelector.classList.add('hidden');

    // Восстанавливаем DropZone
    if (dropZone) {
        dropZone.classList.remove('hidden');

        // Восстанавливаем исходный HTML
        dropZone.innerHTML = `
            <i class="fas fa-file-excel"></i>
            <p>Перетащите Excel файл сюда</p>
            <span>или</span>
            <label for="excelFileInput" class="btn btn-outline" style="cursor: pointer;">
                <i class="fas fa-folder-open"></i> Выбрать файл
            </label>
            <input type="file" id="excelFileInput" accept=".xlsx,.xls" hidden>
        `;

        // === ВАЖНО: Переназначаем слушатель событий на НОВЫЙ input ===
        const newFileInput = document.getElementById('excelFileInput');
        if (newFileInput) {
            newFileInput.addEventListener('change', (e) => {
                if (e.target.files.length > 0) {
                    handleExcelFile(e.target.files[0]);
                }
            });
        }
    }

    state.importData.excelData = null;
}

/**
 * Обработка выбранного Excel файла.
 * @param {File} file - Excel файл
 */
async function handleExcelFile(file) {
    // Проверка расширения
    const validExtensions = ['.xlsx', '.xls'];
    const fileName = file.name.toLowerCase();
    const isValid = validExtensions.some(ext => fileName.endsWith(ext));

    if (!isValid) {
        alert('Пожалуйста, выберите файл Excel (.xlsx или .xls)');
        return;
    }

    // Сохраняем файл для возможности пере-загрузки с другим листом
    state.importData.excelFile = file;

    // Загружаем на сервер
    await uploadExcelFile(file);
}

/**
 * Загрузка Excel файла на сервер.
 * @param {File} file - Excel файл
 * @param {string} [sheet] - Имя листа (опционально)
 */
async function uploadExcelFile(file, sheet = null) {
    const dropZone = document.getElementById('excelDropZone');
    const fileInfo = document.getElementById('excelFileInfo');
    const fileNameEl = document.getElementById('excelFileName');
    const fileStats = document.getElementById('excelFileStats');
    const sheetSelector = document.getElementById('excelSheetSelector');
    const sheetSelect = document.getElementById('excelSheetSelect');

    try {
        // Показываем индикатор загрузки
        if (dropZone) {
            dropZone.innerHTML = '<i class="fas fa-spinner fa-spin"></i><p>Загрузка файла...</p>';
        }

        // Формируем FormData
        const formData = new FormData();
        formData.append('file', file);
        if (sheet) {
            formData.append('sheet', sheet);
        }

        // Отправляем на сервер
        const response = await fetch('/admin/upload_excel', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${state.token}`
            },
            body: formData
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Ошибка загрузки' }));
            throw new Error(errorData.detail || 'Ошибка загрузки файла');
        }

        const data = await response.json();

        // Сохраняем данные
        state.importData.excelData = data;
        state.importData.headers = data.headers;
        state.importData.raw = data.preview;  // Preview для маппинга
        state.importData.cacheKey = data.cache_key;  // Ключ для получения ВСЕХ данных
        state.importData.totalRows = data.total_rows;  // Общее количество строк

        // Обновляем UI
        if (dropZone) dropZone.classList.add('hidden');

        if (fileInfo) {
            fileInfo.classList.remove('hidden');
            if (fileNameEl) fileNameEl.textContent = data.filename || file.name;
            if (fileStats) fileStats.textContent = `${data.total_rows} строк, ${data.headers.length} колонок`;
        }

        // Показываем выбор листа если их несколько
        if (data.sheets && data.sheets.length > 1 && sheetSelector && sheetSelect) {
            sheetSelector.classList.remove('hidden');
            sheetSelect.innerHTML = data.sheets.map(s =>
                `<option value="${s}" ${s === data.selected_sheet ? 'selected' : ''}>${s}</option>`
            ).join('');
        }

        // Переходим к маппингу колонок
        // Инициализация выбора по умолчанию (как в processPastedData)
        state.importData.codeSelection = {};
        if (state.importData.headers.length > 0) {
            state.importData.codeSelection[state.importData.headers[0]] = 1;
        }
        state.importData.descSelection = {};
        state.importData.hierarchySelection = {};

        // Рендерим панели с цифровыми чек-боксами
        renderNumberedCheckboxes(els.mapCodeCols, state.importData.codeSelection, 'code');
        renderNumberedCheckboxes(els.mapDescCols, state.importData.descSelection, 'desc');
        renderNumberedCheckboxes(els.mapHierarchyCols, state.importData.hierarchySelection, 'hierarchy');

        // Рендерим превью таблицы
        renderPreviewTable();
        updateAllPreviews();

        showImportStep('mapping');

    } catch (error) {
        console.error('Excel upload error:', error);
        alert(`Ошибка загрузки Excel: ${error.message}`);

        // Сбрасываем UI в исходное состояние (убираем спиннер)
        resetExcelUploadUI();
    }
}

// === ПРАВИЛА ОЧИСТКИ ДАННЫХ ===

// ПРИМЕЧАНИЕ: Функции загрузки и применения правил вынесены в начало файла (state.cleaningRules)
// Здесь остаются функции рендеринга и управления UI.

/**
 * Рендер списка правил очистки.
 */
function renderCleaningRules() {
    const container = document.getElementById('cleaningRulesList');
    if (!container) return;

    // Используем глобальный state
    if (!state.cleaningRules || state.cleaningRules.length === 0) {
        container.innerHTML = '<p style="color: var(--adm-text-sec); text-align: center; padding: 20px;">Нет правил очистки</p>';
        return;
    }

    container.innerHTML = state.cleaningRules.map((rule, idx) => `
        <div class="cleaning-rule-item ${rule.enabled ? '' : 'disabled'}" data-rule-id="${rule.id}">
            <div class="rule-toggle">
                <label class="toggle-switch">
                    <input type="checkbox" ${rule.enabled ? 'checked' : ''} 
                           onchange="toggleCleaningRule('${rule.id}')">
                    <span class="toggle-slider"></span>
                </label>
            </div>
            <div class="rule-content">
                <div class="rule-name">${escapeHtml(rule.name)}</div>
                <code class="rule-pattern">${escapeHtml(rule.pattern)}</code>
            </div>
            <div class="rule-actions">
                <button class="btn-icon danger" onclick="deleteCleaningRule('${rule.id}')" title="Удалить">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        </div>
    `).join('');
}

/**
 * Переключение активности правила.
 * @param {string} ruleId - ID правила
 */
function toggleCleaningRule(ruleId) {
    const rule = state.cleaningRules.find(r => r.id === ruleId);
    if (rule) {
        rule.enabled = !rule.enabled;
        renderCleaningRules();
    }
}

/**
 * Удаление правила.
 * @param {string} ruleId - ID правила
 */
function deleteCleaningRule(ruleId) {
    if (!confirm('Удалить это правило очистки?')) return;
    state.cleaningRules = state.cleaningRules.filter(r => r.id !== ruleId);
    renderCleaningRules();
}

/**
 * Добавление нового правила очистки.
 */
function addCleaningRule() {
    const nameInput = document.getElementById('newRuleName');
    const patternInput = document.getElementById('newRulePattern');
    const replacementInput = document.getElementById('newRuleReplacement');

    if (!nameInput || !patternInput) return;

    const name = nameInput.value.trim();
    const pattern = patternInput.value.trim();
    const replacement = replacementInput ? replacementInput.value : '';

    if (!name || !pattern) {
        alert('Введите название и regex-паттерн');
        return;
    }

    // Проверяем валидность regex
    try {
        new RegExp(pattern);
    } catch (e) {
        alert(`Невалидный regex: ${e.message}`);
        return;
    }

    // Генерируем уникальный ID
    const id = 'rule_' + Date.now();

    cleaningRules.push({
        id,
        name,
        pattern,
        replacement,
        enabled: true,
        apply_to_columns: ['*']
    });

    // Очищаем форму
    nameInput.value = '';
    patternInput.value = '';
    if (replacementInput) replacementInput.value = '';

    renderCleaningRules();
}

/**
 * Сохранение правил очистки на сервер.
 */
async function saveCleaningRules() {
    try {
        const response = await authFetch('/admin/cleaning_rules', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cleaningRules)
        });

        if (response.ok) {
            alert('Правила очистки сохранены!');
        } else {
            const error = await response.json().catch(() => ({ detail: 'Ошибка' }));
            alert(`Ошибка: ${error.detail}`);
        }
    } catch (error) {
        console.error('Ошибка сохранения правил:', error);
        alert('Ошибка сохранения правил');
    }
}

/**
 * Инициализация управления правилами очистки.
 */
function initCleaningRulesSettings() {
    const addBtn = document.getElementById('addCleaningRuleBtn');
    const saveBtn = document.getElementById('saveCleaningRulesBtn');

    if (addBtn) {
        addBtn.addEventListener('click', addCleaningRule);
    }

    if (saveBtn) {
        saveBtn.addEventListener('click', saveCleaningRules);
    }

    // Загружаем правила
    loadCleaningRules();
}

// Добавляем инициализацию в DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
    initCleaningRulesSettings();
});

/**
 * Валидация маппинга колонок перед импортом.
 * @returns {boolean} True если маппинг валиден
 */
function validateMapping() {
    const codeCols = getOrderedSelection('code');
    const descCols = getOrderedSelection('desc');

    if (codeCols.length === 0) {
        alert('Выберите хотя бы одну колонку для Кода (ID).');
        return false;
    }

    if (descCols.length === 0) {
        alert('Выберите хотя бы одну колонку для Описания.');
        return false;
    }

    return true;
}

/**
 * Получение выбранных колонок в правильном порядке.
 * @param {string} type - Тип: 'code', 'desc', 'hierarchy'
 * @returns {Array<string>} Массив названий колонок в порядке выбора
 */
function getOrderedSelection(type) {
    const selection = type === 'code' ? state.importData.codeSelection :
        type === 'desc' ? state.importData.descSelection :
            state.importData.hierarchySelection;

    // Фильтруем выбранные (order > 0) и сортируем по порядку
    return Object.entries(selection)
        .filter(([_, order]) => order > 0)
        .sort((a, b) => a[1] - b[1])
        .map(([col, _]) => col);
}

/**
 * Загрузка ВСЕХ данных Excel из кэша сервера.
 * Вызывается перед импортом если был загружен Excel файл.
 * @returns {Promise<boolean>} true если данные загружены успешно
 */
async function loadFullExcelData() {
    const cacheKey = state.importData.cacheKey;

    // Если нет cacheKey (CSV/TSV вставка) — пропускаем
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

        // Заменяем preview на полные данные
        state.importData.raw = data.data;

        console.log(`✅ Загружено ${data.total_rows} строк из кэша`);
        return true;

    } catch (error) {
        console.error('Ошибка загрузки данных из кэша:', error);
        alert(`Ошибка загрузки данных: ${error.message}\n\nПопробуйте загрузить файл заново.`);
        return false;
    }
}

/**
 * Формирование записей из сырых данных на основе текущего маппинга.
 * 
 * НОВАЯ ЛОГИКА v2:
 * - description: склеивается через кастомный разделитель (descSeparator)
 * - hierarchy: склеивается через " → " (фиксированный разделитель для категорий)
 * 
 * @returns {Array<Object>} Массив записей {code, description, hierarchy, meta}
 */
function buildRecordsFromMapping() {
    const codeCols = getOrderedSelection('code');
    const descCols = getOrderedSelection('desc');
    const hierarchyCols = getOrderedSelection('hierarchy');
    const codeSeparator = state.importData.codeSeparator || '.';
    const descSeparator = state.importData.descSeparator || ' ';  // Кастомный разделитель описания

    return state.importData.raw.map(row => {
        // Вспомогательная функция для очистки значения ячейки
        const cleanValue = (val) => {
            if (!val) return '';
            // Обрезаем симметричные кавычки если функция уже определена
            if (typeof stripSymmetricQuotes === 'function') {
                return stripSymmetricQuotes(String(val).trim());
            }
            return String(val).trim();
        };

        // Склеиваем код (обрезаем кавычки из каждой ячейки)
        const code = codeCols.map(c => cleanValue(row[c])).filter(Boolean).join(codeSeparator);

        // Склеиваем описание через кастомный разделитель (обрезаем кавычки)
        let description = descCols.map(c => cleanValue(row[c])).filter(Boolean).join(descSeparator);
        // User requested NOT to clean description for materials, only folders
        // description = applyCleaningRules(description, 'description');

        // Склеиваем иерархию через " → " (фиксированный разделитель для категорий каталога)
        let hierarchy = null;
        if (hierarchyCols.length > 0) {
            // Каждую часть иерархии чистим ОТДЕЛЬНО, чтобы правила (например ^Раздел) работали для каждого уровня
            const parts = hierarchyCols.map(c => {
                let val = cleanValue(row[c]);
                val = applyCleaningRules(val, 'hierarchy'); // Чистим каждый уровень!
                return val;
            }).filter(Boolean);

            hierarchy = parts.join(' → ');
        }

        return {
            code,
            description,
            hierarchy,
            meta: row
        };
    }).filter(r => r.code && r.description); // Фильтруем пустые
}

// === NUMBERED CHECKBOXES (Цифровые чек-боксы) ===

/**
 * Рендеринг списка цифровых чек-боксов для панели.
 * @param {HTMLElement} container - Контейнер для чек-боксов
 * @param {Object} selection - Объект состояния выбора {colName: order}
 * @param {string} type - Тип панели: 'code', 'desc', 'hierarchy'
 * @param {number} defaultFirstN - Сколько первых выбрать по умолчанию (0 = никакие)
 */
function renderNumberedCheckboxes(container, selection, type, defaultFirstN = 0) {
    if (!container) return;

    container.innerHTML = state.importData.headers.map((header, idx) => {
        const order = selection[header] || 0;
        const isSelected = order > 0;

        return `
            <div class="numbered-option ${isSelected ? 'selected' : ''}" 
                 data-column="${header}" 
                 data-type="${type}">
                <div class="num-badge">${isSelected ? order : ''}</div>
                <span class="num-label" title="${header}">${header}</span>
            </div>
        `;
    }).join('');

    // Добавляем обработчики кликов
    container.querySelectorAll('.numbered-option').forEach(option => {
        option.addEventListener('click', () => handleNumberedClick(option, type));
    });
}

/**
 * Обработка клика по цифровому чек-боксу.
 * Если не выбран - назначает следующий номер.
 * Если выбран - снимает выбор и перенумеровывает остальные.
 */
function handleNumberedClick(option, type) {
    const column = option.dataset.column;
    const selection = type === 'code' ? state.importData.codeSelection :
        type === 'desc' ? state.importData.descSelection :
            state.importData.hierarchySelection;

    const currentOrder = selection[column] || 0;

    if (currentOrder > 0) {
        // Снимаем выбор
        selection[column] = 0;

        // Перенумеровываем: все номера > currentOrder уменьшаем на 1
        Object.keys(selection).forEach(col => {
            if (selection[col] > currentOrder) {
                selection[col]--;
            }
        });
    } else {
        // Назначаем следующий номер
        const maxOrder = Math.max(0, ...Object.values(selection));
        selection[column] = maxOrder + 1;
    }

    // Перерисовываем панель
    const container = type === 'code' ? els.mapCodeCols :
        type === 'desc' ? els.mapDescCols :
            els.mapHierarchyCols;

    renderNumberedCheckboxes(container, selection, type);
    updateAllPreviews();
}

/**
 * Поиск первого непустого значения для колонки среди всех строк данных.
 * @param {string} columnName - Имя колонки
 * @returns {string} Первое непустое значение или "Пример" если колонка пустая
 */
function findFirstNonEmptyValue(columnName) {
    for (const row of state.importData.raw) {
        const value = row[columnName];
        if (value && value.trim()) {
            return value.trim();
        }
    }
    // Колонка полностью пустая - возвращаем placeholder
    return 'Пример';
}

/**
 * Обновление всех превью склеенных значений.
 * Для каждой колонки ищет первое непустое значение среди всех строк.
 * Если колонка полностью пустая - подставляет "Пример".
 */
function updateAllPreviews() {
    if (state.importData.raw.length === 0) return;

    const codeSeparator = state.importData.codeSeparator || '.';
    const descSeparator = state.importData.descSeparator || ' ';  // Кастомный разделитель описания

    // Превью кода - ищем первые непустые значения для каждой колонки
    const codeCols = getOrderedSelection('code');
    const codeValues = codeCols.map(c => findFirstNonEmptyValue(c));
    const codeValue = codeValues.join(codeSeparator);
    if (els.codePreview) {
        const codeEl = els.codePreview.querySelector('code');
        codeEl.textContent = codeValue || '—';
        codeEl.title = codeValue || '';
    }

    // Превью описания - используем кастомный разделитель
    const descCols = getOrderedSelection('desc');
    const descValues = descCols.map(c => findFirstNonEmptyValue(c));
    const descValue = descValues.join(descSeparator);
    if (els.descPreview) {
        const descEl = els.descPreview.querySelector('code');
        descEl.textContent = descValue || '—';
        descEl.title = descValue || '';
    }

    // Превью иерархии - ищем первые непустые значения для каждой колонки
    const hierarchyCols = getOrderedSelection('hierarchy');
    if (els.hierarchyPreview) {
        const hierarchyEl = els.hierarchyPreview.querySelector('code');

        if (hierarchyCols.length === 0) {
            // Иерархия не выбрана - показываем что будет использоваться описание
            if (descCols.length > 0) {
                hierarchyEl.innerHTML = '<i class="fas fa-link" style="opacity:0.5; margin-right:4px;"></i>как описание';
                hierarchyEl.title = 'Будет использоваться колонка Описания';
            } else {
                hierarchyEl.textContent = '—';
                hierarchyEl.title = 'Выберите колонки описания или иерархии';
            }
        } else {
            // Иерархия выбрана - показываем компактно через " / "
            // Для каждой колонки ищем первое непустое значение
            const hierarchyValues = hierarchyCols.map(c => findFirstNonEmptyValue(c));
            const hierarchyCompact = hierarchyValues.join(' / ');
            hierarchyEl.textContent = hierarchyCompact;
            hierarchyEl.title = hierarchyValues.join(' → ');
        }
    }
}

// === DATA PARSING ===

function getSelectedDelimiter() {
    const selected = document.querySelector('input[name="delimiter"]:checked');
    return selected ? selected.value : 'tab';
}

function detectDelimiter(text) {
    const firstLine = text.split('\n')[0] || '';
    const tabCount = (firstLine.match(/\t/g) || []).length;
    const semicolonCount = (firstLine.match(/;/g) || []).length;
    const commaCount = (firstLine.match(/,/g) || []).length;

    if (tabCount >= semicolonCount && tabCount >= commaCount && tabCount > 0) {
        return '\t';
    } else if (semicolonCount >= commaCount && semicolonCount > 0) {
        return ';';
    } else if (commaCount > 0) {
        return ',';
    }
    return '\t';
}

/**
 * Обработка вставленных данных.
 * Парсит CSV/TSV и переходит к шагу маппинга.
 */
function processPastedData(text) {
    let delimiterValue = getSelectedDelimiter();
    let delimiter;

    if (delimiterValue === 'auto') {
        delimiter = detectDelimiter(text);
        console.log('Авто-определён разделитель:', delimiter === '\t' ? 'Tab' : delimiter);
    } else if (delimiterValue === 'tab') {
        delimiter = '\t';
    } else {
        delimiter = delimiterValue;
    }

    // Используем полноценный CSV парсер вместо простого split
    // Это корректно обрабатывает экранированные кавычки ("") и разделители внутри кавычек
    const rows = parseCSV(text, delimiter);

    if (rows.length < 2) {
        alert('Недостаточно данных. Нужна минимум 1 строка заголовков и 1 строка данных.\n\nПроверьте выбранный разделитель!');
        return;
    }

    if (rows[0].length === 1) {
        alert('Обнаружена только 1 колонка. Возможно, выбран неверный разделитель.\n\nПопробуйте другой разделитель или "Авто".');
        return;
    }

    // Парсим заголовки и данные
    state.importData.headers = rows[0].map(h => h.trim()).filter(h => h);
    state.importData.raw = rows.slice(1).map(row => {
        const obj = {};
        state.importData.headers.forEach((h, i) => obj[h] = (row[i] || '').trim());
        return obj;
    }).filter(obj => Object.values(obj).some(v => v));

    // Инициализация выбора по умолчанию
    // Код: только первая колонка = 1
    state.importData.codeSelection = {};
    if (state.importData.headers.length > 0) {
        state.importData.codeSelection[state.importData.headers[0]] = 1;
    }

    // Описание: пустое по умолчанию (пользователь сам выбирает колонки)
    state.importData.descSelection = {};

    // Иерархия: пустая (будет использоваться описание)
    state.importData.hierarchySelection = {};

    // Рендерим панели с цифровыми чек-боксами
    renderNumberedCheckboxes(els.mapCodeCols, state.importData.codeSelection, 'code');
    renderNumberedCheckboxes(els.mapDescCols, state.importData.descSelection, 'desc');
    renderNumberedCheckboxes(els.mapHierarchyCols, state.importData.hierarchySelection, 'hierarchy');

    // Рендерим превью таблицы
    renderPreviewTable();
    updateAllPreviews();

    showImportStep('mapping');
}

/**
 * Полноценный CSV парсер по RFC 4180.
 * 
 * Корректно обрабатывает:
 * - Поля в кавычках: "значение"
 * - Экранированные кавычки внутри полей: "текст ""кавычки"" текст" → текст "кавычки" текст
 * - Разделители внутри кавычек: "a;b;c" → одно поле
 * - Многострочные поля в кавычках
 * 
 * @param {string} text - Исходный CSV/TSV текст
 * @param {string} delimiter - Разделитель полей (запятая, точка с запятой, табуляция)
 * @returns {Array<Array<string>>} Массив строк, каждая строка — массив полей
 */
function parseCSV(text, delimiter) {
    const rows = [];
    let currentRow = [];
    let currentField = '';
    let inQuotes = false;
    let i = 0;

    // Нормализуем переносы строк
    text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

    while (i < text.length) {
        const char = text[i];
        const nextChar = text[i + 1];

        if (inQuotes) {
            // Внутри кавычек
            if (char === '"') {
                if (nextChar === '"') {
                    // Экранированная кавычка "" → "
                    currentField += '"';
                    i += 2;
                } else {
                    // Закрывающая кавычка
                    inQuotes = false;
                    i++;
                }
            } else {
                // Обычный символ внутри кавычек
                currentField += char;
                i++;
            }
        } else {
            // Вне кавычек
            if (char === '"') {
                // Открывающая кавычка
                inQuotes = true;
                i++;
            } else if (char === delimiter) {
                // Разделитель полей
                currentRow.push(currentField);
                currentField = '';
                i++;
            } else if (char === '\n') {
                // Конец строки
                currentRow.push(currentField);
                if (currentRow.some(cell => cell.trim())) {
                    rows.push(currentRow);
                }
                currentRow = [];
                currentField = '';
                i++;
            } else {
                // Обычный символ
                currentField += char;
                i++;
            }
        }
    }

    // Добавляем последнее поле и строку
    if (currentField || currentRow.length > 0) {
        currentRow.push(currentField);
        if (currentRow.some(cell => cell.trim())) {
            rows.push(currentRow);
        }
    }

    return rows;
}

function renderPreviewTable() {
    els.previewHead.innerHTML = `<tr>${state.importData.headers.map(h => `<th>${h}</th>`).join('')}</tr>`;

    const previewRows = state.importData.raw.slice(0, 5);
    els.previewBody.innerHTML = previewRows.map(row =>
        `<tr>${state.importData.headers.map(h => `<td title="${row[h] || ''}">${row[h] || '-'}</td>`).join('')}</tr>`
    ).join('');

    els.previewCount.innerText = `${state.importData.raw.length} строк`;
}

// === IMPORT STEP NAVIGATION ===

/**
 * Переключение шага визарда импорта.
 * @param {string} stepName - Имя шага: 'paste', 'mapping', 'diff', 'progress'
 */
function showImportStep(stepName) {
    // Скрываем все шаги
    Object.values(els.importSteps).forEach(s => {
        if (s) s.classList.remove('active');
    });

    // Показываем нужный шаг
    if (els.importSteps[stepName]) {
        els.importSteps[stepName].classList.add('active');
    }

    // Управление кнопками
    const btns = els.importBtns;

    // Сначала скрываем все
    btns.back.classList.add('hidden');
    btns.next.classList.add('hidden');
    btns.compare.classList.add('hidden');
    btns.upload.classList.add('hidden');
    btns.apply.classList.add('hidden');

    // Показываем нужные кнопки для каждого шага
    switch (stepName) {
        case 'paste':
            btns.next.classList.remove('hidden');
            break;

        case 'mapping':
            btns.back.classList.remove('hidden');
            btns.compare.classList.remove('hidden');
            btns.upload.classList.remove('hidden');
            break;

        case 'diff':
            btns.back.classList.remove('hidden');
            btns.apply.classList.remove('hidden');
            break;

        case 'progress':
            // Никаких кнопок во время загрузки
            break;
    }
}

// === DIFF ANALYSIS (Анализ изменений) ===

/**
 * Обрезка симметричных кавычек с обоих концов строки.
 * 
 * Поддерживаемые пары кавычек:
 * - Двойные: "..." и «...»
 * - Одинарные: '...'
 * - Типографские: „..." и "..."
 * 
 * Рекурсивно удаляет все парные кавычки.
 * 
 * @param {string} text - Исходный текст
 * @returns {string} Текст без симметричных кавычек
 */
function stripSymmetricQuotes(text) {
    if (!text || text.length < 2) return text || '';

    // Пары кавычек: [открывающая, закрывающая]
    const quotePairs = [
        ['"', '"'],     // Обычные двойные кавычки
        ["'", "'"],     // Одинарные кавычки
        ['«', '»'],     // Французские кавычки (ёлочки)
        ['„', '"'],     // Немецкие типографские кавычки
        ['"', '"'],     // Английские типографские кавычки
        ['`', '`'],     // Обратные кавычки
    ];

    let result = text.trim();
    let changed = true;

    // Рекурсивно убираем все парные кавычки
    while (changed && result.length >= 2) {
        changed = false;
        for (const [open, close] of quotePairs) {
            if (result.startsWith(open) && result.endsWith(close)) {
                result = result.slice(open.length, -close.length).trim();
                changed = true;
                break; // Начинаем проверку заново
            }
        }
    }

    return result;
}

/**
 * Нормализация текста для корректного сравнения.
 * Порт из Python скрипта 03_update_qdrant_collection.py
 * 
 * Убирает различия которые не влияют на смысл:
 * - Симметричные кавычки с обоих концов
 * - Разные переносы строк (Windows \r\n vs Unix \n)
 * - Множественные пробелы и табуляции
 * - Пробелы в начале/конце строк
 * - Пустые строки
 * - Приводит к нижнему регистру
 */
function normalizeText(text) {
    if (!text) return '';

    // Сначала обрезаем симметричные кавычки
    let normalized = stripSymmetricQuotes(text);

    return normalized.toLowerCase()
        .replace(/\r\n/g, '\n')
        .replace(/\r/g, '\n')
        .replace(/[ \t]+/g, ' ')
        .split('\n')
        .map(line => line.trim())
        .filter(line => line)
        .join('\n')
        .trim();
}

/**
 * Анализ изменений между новыми и существующими записями.
 * Порт из Python скрипта 03_update_qdrant_collection.py
 * 
 * @param {Array<Object>} newRecords - Новые записи [{code, description}]
 * @param {Object} existingRecords - Существующие записи {code: {description, path_depth, path_level_N}}
 * @returns {Object} Результат анализа {added, modified, deleted, unchanged}
 */
function analyzeChanges(newRecords, existingRecords) {
    const result = {
        added: [],
        modified: [],
        deleted: [],
        unchanged: 0
    };

    const newCodes = new Set(newRecords.map(r => r.code));
    const existingCodes = new Set(Object.keys(existingRecords));

    // Хелпер: извлечь описание из записи (поддержка нового формата объектов и старого строкового)
    const getDescription = (record) => {
        if (typeof record === 'string') return record;
        return record?.description || record?.full_description || '';
    };

    // 1. Новые записи (код есть в новых, но нет в существующих)
    newRecords.forEach(record => {
        if (!existingCodes.has(record.code)) {
            result.added.push(record);
        }
    });

    // 2. Изменённые записи (код есть в обоих, но описание отличается после нормализации)
    newRecords.forEach(record => {
        if (existingCodes.has(record.code)) {
            const oldDesc = getDescription(existingRecords[record.code]);
            const newDesc = record.description || '';

            const oldNormalized = normalizeText(oldDesc);
            const newNormalized = normalizeText(newDesc);

            if (oldNormalized !== newNormalized) {
                result.modified.push({
                    code: record.code,
                    oldDescription: oldDesc,
                    newDescription: record.description,
                    hierarchy: record.hierarchy
                });
            } else {
                result.unchanged++;
            }
        }
    });

    // 3. Удалённые записи (код есть в существующих, но нет в новых)
    existingCodes.forEach(code => {
        if (!newCodes.has(code)) {
            result.deleted.push({
                code: code,
                description: getDescription(existingRecords[code])
            });
        }
    });

    console.log(`📊 Анализ изменений: +${result.added.length} добавлено, ~${result.modified.length} изменено, -${result.deleted.length} удалено, =${result.unchanged} без изменений`);

    return result;
}

/**
 * Извлечение уникальных папок из записей материалов.
 * 
 * Каждый материал имеет hierarchy (путь каталога), который разбивается на папки.
 * Например: "Приборы → Аннотации → 2D узлы" создаёт 3 папки:
 *   - "Приборы"
 *   - "Приборы → Аннотации"  
 *   - "Приборы → Аннотации → 2D узлы"
 * 
 * @param {Array<Object>} records - Записи материалов с полем hierarchy
 * @returns {Object} Словарь {full_path: {leaf_name, items_count}}
 */
function extractFoldersFromRecords(records) {
    const folderMap = {};  // {full_path: {leaf_name, items_count}}

    records.forEach(record => {
        const hierarchy = record.hierarchy || '';
        if (!hierarchy) return;

        const parts = hierarchy.split(' → ').map(p => p.trim()).filter(Boolean);

        let currentPath = '';
        parts.forEach((part, idx) => {
            currentPath = idx === 0 ? part : currentPath + ' → ' + part;

            if (!folderMap[currentPath]) {
                folderMap[currentPath] = {
                    full_path: currentPath,
                    leaf_name: part,
                    items_count: 0,
                    level: idx + 1
                };
            }

            if (idx === parts.length - 1) {
                folderMap[currentPath].items_count++;
            }
        });
    });

    return folderMap;
}

/**
 * Нормализация пути для корректного сравнения.
 * Убирает лишние пробелы и стандартизирует разделители.
 */
function normalizePath(path) {
    if (!path) return '';
    return path.split(' → ')
        .map(p => p.trim())
        .filter(Boolean)
        .join(' → ');
}

/**
 * Анализ изменений папок каталога.
 * 
 * Сравнивает папки, извлечённые из импортируемых данных, с текущими папками в базе.
 * Определяет:
 * - Новые папки (будут созданы с эмбеддингами)
 * - Изменённые папки (изменилось количество материалов)
 * - Удалённые папки (осиротевшие, без материалов)
 * 
 * @param {Array<Object>} newRecords - Новые записи материалов
 * @param {Object} existingFolders - Текущие папки из базы {full_path: {leaf_name, items_count}}
 * @returns {Object} {added: [], modified: [], deleted: []}
 */
function analyzeFolderChanges(newRecords, existingFolders) {
    const result = {
        added: [],
        modified: [],
        deleted: []
    };

    // Извлекаем папки из новых записей
    const newFolders = extractFoldersFromRecords(newRecords);

    // Нормализованные пути для сравнения
    const existingPaths = new Set(Object.keys(existingFolders).map(normalizePath));
    const newPaths = Object.keys(newFolders);

    // Фильтруем: только папки с материалами (items_count > 0)
    const leafFolderPaths = newPaths.filter(p => newFolders[p].items_count > 0);

    // 1. Новые папки - путь НЕ существует в базе И содержит материалы
    leafFolderPaths.forEach(rawPath => {
        const path = normalizePath(rawPath);

        if (!existingPaths.has(path)) {
            const folderData = newFolders[rawPath];
            result.added.push({
                full_path: rawPath,
                leaf_name: folderData.leaf_name,
                items_count: folderData.items_count,
                level: folderData.level
            });
        }
    });

    // 2. Удалённые папки
    const newPathsSet = new Set(newPaths.map(normalizePath));

    Object.keys(existingFolders).forEach(rawExistingPath => {
        const path = normalizePath(rawExistingPath);

        if (!newPathsSet.has(path)) {
            const folderData = existingFolders[rawExistingPath];
            const leafName = folderData.leaf_name || path.split(' → ').pop();

            result.deleted.push({
                full_path: rawExistingPath,
                leaf_name: leafName,
                items_count: folderData.items_count || 0
            });
        }
    });

    // Сортируем
    result.added.sort((a, b) => a.level - b.level || a.full_path.localeCompare(b.full_path));
    result.deleted.sort((a, b) => a.full_path.localeCompare(b.full_path));

    return result;
}

/**
 * Выполнение diff-анализа: загрузка текущих записей и сравнение.
 */
async function performDiffAnalysis() {
    // Если был загружен Excel — подгружаем ВСЕ данные из кэша (не только preview)
    if (state.importData.cacheKey) {
        const loaded = await loadFullExcelData();
        if (!loaded) return;  // Ошибка загрузки — прерываем
    }

    // Показываем индикатор загрузки
    showImportStep('diff');
    els.diffLoading.classList.remove('hidden');
    els.diffTableBody.innerHTML = '';
    els.diffEmpty.classList.add('hidden');

    try {
        // === ШАГ 1: Загружаем все текущие записи (материалы) из коллекции ===
        console.log(`📥 Загрузка текущих записей из коллекции '${state.activeCollection}'...`);

        // Гарантируем наличие правил очистки
        if (!state.cleaningRules || state.cleaningRules.length === 0) {
            console.log('⚠️ Правила очистки не загружены, загружаем...');
            await loadCleaningRules();
        }

        const res = await fetch(`/get_all_codes?database=${state.activeCollection}`);
        if (!res.ok) {
            throw new Error('Не удалось загрузить текущие записи');
        }

        const data = await res.json();
        state.diffData.existingRecords = data.records || {};

        console.log(`✅ Загружено ${Object.keys(state.diffData.existingRecords).length} записей из базы`);

        // === ШАГ 2: ИЗВЛЕКАЕМ папки из существующих записей (НЕ из отдельного API) ===
        // ИСПРАВЛЕНИЕ: API /get_all_folders возвращает только записи с is_folder=true,
        // но в базе папки могут не иметь этот флаг (старый импорт).
        // Каталог на главной строит папки динамически из path_level_N полей материалов.
        // Поэтому для корректного сравнения извлекаем папки ИЗ МАТЕРИАЛОВ так же,
        // как это делается для импортируемых данных.

        console.log(`📁 Извлечение папок из существующих материалов...`);

        // Преобразуем существующие записи в формат для extractFoldersFromRecords
        const existingRecordsArray = Object.values(state.diffData.existingRecords).map(record => {
            // Восстанавливаем hierarchy из path_level_N
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
                hierarchy: hierarchy
            };
        });

        // Извлекаем папки из существующих записей (та же логика что для новых)
        state.diffData.existingFolders = extractFoldersFromRecords(existingRecordsArray);

        // Формируем записи из импортируемых данных
        const newRecords = buildRecordsFromMapping();

        // === ШАГ 3: Выполняем анализ материалов ===
        const diff = analyzeChanges(newRecords, state.diffData.existingRecords);

        state.diffData.added = diff.added;
        state.diffData.modified = diff.modified;
        state.diffData.deleted = diff.deleted;
        state.diffData.unchanged = diff.unchanged;

        // === ШАГ 4: Выполняем анализ папок ===
        const folderDiff = analyzeFolderChanges(newRecords, state.diffData.existingFolders);
        state.diffData.folderChanges = folderDiff;

        console.log(`📊 Анализ: +${diff.added.length} добавлено, ~${diff.modified.length} изменено, -${diff.deleted.length} удалено | Папки: +${folderDiff.added.length} новых`);

        // Обновляем UI
        updateDiffUI();

    } catch (e) {
        console.error('❌ Ошибка diff-анализа:', e);
        alert('Ошибка загрузки данных из базы: ' + e.message);
        showImportStep('mapping');
    } finally {
        els.diffLoading.classList.add('hidden');
    }
}

/**
 * Обновление UI diff-шага на основе результатов анализа.
 */
function updateDiffUI() {
    const { added, modified, deleted, unchanged, folderChanges } = state.diffData;

    // === СЧЁТЧИКИ МАТЕРИАЛОВ ===
    els.diffAddedCount.textContent = added.length;
    els.diffModifiedCount.textContent = modified.length;
    els.diffDeletedCount.textContent = deleted.length;

    // Обновляем badges в табах материалов
    els.diffAddedBadge.textContent = added.length;
    els.diffModifiedBadge.textContent = modified.length;
    els.diffDeletedBadge.textContent = deleted.length;

    // === СЧЁТЧИКИ ПАПОК ===
    const totalFolderChanges = folderChanges.added.length + folderChanges.modified.length + folderChanges.deleted.length;
    if (els.diffFoldersCount) {
        els.diffFoldersCount.textContent = totalFolderChanges;
    }
    if (els.diffFoldersBadge) {
        els.diffFoldersBadge.textContent = totalFolderChanges;
    }

    // Показываем/скрываем предупреждение об удалениях
    if (deleted.length > 0) {
        els.diffDeleteWarning.classList.remove('hidden');
    } else {
        els.diffDeleteWarning.classList.add('hidden');
    }

    // Показываем первый таб с данными (приоритет: added > modified > deleted > folders)
    if (added.length > 0) {
        state.diffActiveTab = 'added';
    } else if (modified.length > 0) {
        state.diffActiveTab = 'modified';
    } else if (deleted.length > 0) {
        state.diffActiveTab = 'deleted';
    } else if (totalFolderChanges > 0) {
        state.diffActiveTab = 'folders';
    } else {
        state.diffActiveTab = 'added';
    }

    // Обновляем активный таб
    updateDiffTabUI();
    renderDiffTable();
}

/**
 * Инициализация обработчиков табов diff.
 */
function initDiffTabs() {
    document.querySelectorAll('.diff-tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            state.diffActiveTab = btn.dataset.tab;
            updateDiffTabUI();
            renderDiffTable();
        });
    });
}

/**
 * Обновление визуального состояния табов diff.
 */
function updateDiffTabUI() {
    document.querySelectorAll('.diff-tab-btn').forEach(btn => {
        if (btn.dataset.tab === state.diffActiveTab) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
}

/**
 * Рендеринг таблицы diff для активного таба.
 */
function renderDiffTable() {
    const { added, modified, deleted, folderChanges } = state.diffData;

    // === ВКЛАДКА ПАПКИ ===
    if (state.diffActiveTab === 'folders') {
        renderFoldersDiffTable();
        return;
    }

    // === ВКЛАДКИ МАТЕРИАЛОВ ===
    let data = [];

    switch (state.diffActiveTab) {
        case 'added':
            data = added;
            break;
        case 'modified':
            data = modified;
            break;
        case 'deleted':
            data = deleted;
            break;
    }

    if (data.length === 0) {
        els.diffTableBody.innerHTML = '';
        els.diffEmpty.classList.remove('hidden');
        return;
    }

    els.diffEmpty.classList.add('hidden');

    // Рендерим строки таблицы
    els.diffTableBody.innerHTML = data.slice(0, 100).map(record => {
        const code = record.code || '';

        if (state.diffActiveTab === 'modified') {
            // Для изменённых показываем старое и новое
            return `
                <tr>
                    <td class="code-col">${escapeHtml(code)}</td>
                    <td class="desc-col">
                        <span class="diff-old">${escapeHtml(truncate(record.oldDescription, 150))}</span>
                        <span class="diff-arrow">↓</span>
                        <span class="diff-new">${escapeHtml(truncate(record.newDescription, 150))}</span>
                    </td>
                </tr>
            `;
        } else {
            // Для добавленных и удалённых - просто описание
            const desc = record.description || record.newDescription || '';
            return `
                <tr>
                    <td class="code-col">${escapeHtml(code)}</td>
                    <td class="desc-col">${escapeHtml(truncate(desc, 200))}</td>
                </tr>
            `;
        }
    }).join('');

    // Если записей больше 100, показываем сообщение
    if (data.length > 100) {
        els.diffTableBody.innerHTML += `
            <tr>
                <td colspan="2" style="text-align: center; color: var(--adm-text-sec); padding: 15px;">
                    ... и ещё ${data.length - 100} записей
                </td>
            </tr>
        `;
    }
}

/**
 * Рендеринг таблицы папок в diff.
 * 
 * Понятная структура с чёткими колонками:
 * - Название папки (крупно) + путь (мелко)
 * - Статус: что изменилось
 * - Материалов: было → стало
 */
function renderFoldersDiffTable() {
    const { folderChanges } = state.diffData;
    const { added, modified, deleted } = folderChanges;

    const totalChanges = added.length + modified.length + deleted.length;

    if (totalChanges === 0) {
        els.diffTableBody.innerHTML = '';
        els.diffEmpty.classList.remove('hidden');
        return;
    }

    els.diffEmpty.classList.add('hidden');

    let html = '';

    // === ДОБАВЛЕННЫЕ ПАПКИ (зелёный) ===
    if (added.length > 0) {
        html += `
            <tr class="folder-section-header">
                <td colspan="3" style="background: var(--adm-success-bg); color: var(--adm-success); font-weight: 600; padding: 10px 15px;">
                    <i class="fas fa-plus-circle"></i> Новые папки — ${added.length} шт.
                </td>
            </tr>
            <tr class="folder-table-subheader">
                <th style="width: 40%;">Название папки</th>
                <th style="width: 40%;">Статус</th>
                <th style="width: 20%;">Материалов</th>
            </tr>
        `;
        added.slice(0, 50).forEach(folder => {
            html += `
                <tr class="folder-added">
                    <td>
                        <div class="folder-name-cell">
                            <span class="folder-leaf-name">${escapeHtml(folder.leaf_name)}</span>
                            <span class="folder-full-path"><i class="fas fa-folder-open"></i> ${escapeHtml(folder.full_path)}</span>
                        </div>
                    </td>
                    <td><span class="status-badge status-new">Новая папка</span></td>
                    <td class="folder-count-cell">${folder.items_count}</td>
                </tr>
            `;
        });
        if (added.length > 50) {
            html += `<tr><td colspan="3" class="folder-more-row">... и ещё ${added.length - 50} папок</td></tr>`;
        }
    }

    // === ПЕРЕИМЕНОВАННЫЕ ПАПКИ (жёлтый) - изменилось название папки ===
    if (modified.length > 0) {
        html += `
            <tr class="folder-section-header">
                <td colspan="3" style="background: #fef3c7; color: #d97706; font-weight: 600; padding: 10px 15px;">
                    <i class="fas fa-pen"></i> Переименованные папки — ${modified.length} шт.
                </td>
            </tr>
            <tr class="folder-table-subheader">
                <th style="width: 40%;">Новое название</th>
                <th style="width: 40%;">Было</th>
                <th style="width: 20%;">Материалов</th>
            </tr>
        `;
        modified.slice(0, 50).forEach(folder => {
            html += `
                <tr class="folder-modified">
                    <td>
                        <div class="folder-name-cell">
                            <span class="folder-leaf-name">${escapeHtml(folder.leaf_name)}</span>
                            <span class="folder-full-path"><i class="fas fa-folder-open"></i> ${escapeHtml(folder.full_path)}</span>
                        </div>
                    </td>
                    <td>
                        <div class="folder-name-cell">
                            <span class="folder-leaf-name" style="text-decoration: line-through; opacity: 0.7;">${escapeHtml(folder.old_leaf_name || '')}</span>
                            <span class="folder-full-path" style="opacity: 0.5;"><i class="fas fa-folder-open"></i> ${escapeHtml(folder.old_path || '')}</span>
                        </div>
                    </td>
                    <td class="folder-count-cell">${folder.items_count}</td>
                </tr>
            `;
        });
        if (modified.length > 50) {
            html += `<tr><td colspan="3" class="folder-more-row">... и ещё ${modified.length - 50} папок</td></tr>`;
        }
    }

    // === УДАЛЁННЫЕ ПАПКИ (красный) - осиротевшие, без материалов ===
    if (deleted.length > 0) {
        html += `
            <tr class="folder-section-header">
                <td colspan="3" style="background: var(--adm-danger-bg); color: var(--adm-danger); font-weight: 600; padding: 10px 15px;">
                    <i class="fas fa-trash-alt"></i> Удаляемые папки — ${deleted.length} шт. (нет материалов)
                </td>
            </tr>
            <tr class="folder-table-subheader">
                <th style="width: 40%;">Название папки</th>
                <th style="width: 40%;">Причина</th>
                <th style="width: 20%;">Было мат.</th>
            </tr>
        `;
        deleted.slice(0, 50).forEach(folder => {
            html += `
                <tr class="folder-deleted">
                    <td>
                        <div class="folder-name-cell">
                            <span class="folder-leaf-name">${escapeHtml(folder.leaf_name)}</span>
                            <span class="folder-full-path"><i class="fas fa-folder-open"></i> ${escapeHtml(folder.full_path)}</span>
                        </div>
                    </td>
                    <td><span class="status-badge status-deleted">Папка осиротела — нет материалов</span></td>
                    <td class="folder-count-cell"><span class="count-old">${folder.items_count}</span></td>
                </tr>
            `;
        });
        if (deleted.length > 50) {
            html += `<tr><td colspan="3" class="folder-more-row">... и ещё ${deleted.length - 50} папок</td></tr>`;
        }
    }

    els.diffTableBody.innerHTML = html;
}

/**
 * Экранирование HTML.
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Обрезка текста с добавлением "..."
 */
function truncate(text, maxLength) {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
}

// === IMPORT EXECUTION ===

/**
 * Полная загрузка всех записей (перезапись).
 */
async function performFullUpload() {
    // Если был загружен Excel — загружаем ВСЕ данные на СЕРВЕР через /admin/upload_excel
    // (если ещё не загружено), получаем cache_key и передаём только его в /admin/import.
    // Это решает проблему огромных payload (142k строк = 28 MB JSON в Celery).
    let cacheKey = state.importData.cacheKey;

    if (state.importData.excelFile && !cacheKey) {
        // Excel файл загружен через UI но ещё не отправлен на сервер
        const loaded = await uploadExcelFileToServer();
        if (!loaded) return;
        cacheKey = loaded;
    }

    if (!cacheKey) {
        // Нет Excel — собираем записи вручную (fallback)
        const records = buildRecordsFromMapping();
        if (records.length === 0) {
            alert('Нет записей для загрузки. Сначала загрузите Excel.');
            return;
        }
        // Используем старый путь с records (для теста / небольших данных)
        const hierarchyCols = getOrderedSelection('hierarchy');
        const payload = {
            collection_name: state.activeCollection,
            records: records.map(r => ({
                code: r.code,
                description: r.description,
                hierarchy: hierarchyCols.length > 0 ? r.hierarchy : undefined,
                meta: r.meta
            })),
            recreate: false
        };
        showImportStep('progress');
        els.importStatusText.innerText = 'Отправка задачи...';
        try {
            const res = await authFetch('/admin/import', {
                method: 'POST',
                body: JSON.stringify(payload)
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

    // Импорт через cache_key (оптимально для больших файлов)
    // Собираем column_mapping из UI selection
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
        code_separator: state.importData.codeSeparator || '.',
        description_separator: state.importData.descSeparator || ' '
    };
    console.log('[performFullUpload] columnMapping:', columnMapping);

    const payload = {
        collection_name: state.activeCollection,
        cache_key: cacheKey,
        column_mapping: columnMapping,
        recreate: false
    };

    showImportStep('progress');
    els.importStatusText.innerText = 'Отправка задачи (через cache_key)...';

    try {
        const res = await authFetch('/admin/import', {
            method: 'POST',
            body: JSON.stringify(payload)
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
 * Загрузить Excel файл на сервер, получить cache_key.
 * Возвращает cache_key или null при ошибке.
 */
async function uploadExcelFileToServer() {
    if (!state.importData.excelFile) return null;
    const fd = new FormData();
    fd.append('file', state.importData.sourceFile);
    els.importStatusText.innerText = 'Загрузка файла на сервер...';
    try {
        const res = await authFetch('/admin/upload_excel', {
            method: 'POST',
            body: fd  // НЕ устанавливать Content-Type — браузер сам добавит multipart boundary
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Ошибка загрузки файла');
        }
        const json = await res.json();
        state.importData.cacheKey = json.cache_key;
        return json.cache_key;
    } catch (e) {
        alert('Ошибка загрузки файла: ' + e.message);
        return null;
    }
}

/**
 * Применение точечных изменений (diff-режим).
 * Использует /admin/import для корректной генерации path_level_N (иерархии каталога).
 * 
 * ВАЖНО: Учитывает изменения как материалов, так и папок.
 * Папки обновляются автоматически при импорте материалов.
 */
async function applyDiffChanges() {
    const { added, modified, deleted, folderChanges } = state.diffData;

    // Подсчёт изменений материалов
    const materialChanges = added.length + modified.length + deleted.length;

    // Подсчёт изменений папок
    const folderChangesCount = folderChanges.added.length + folderChanges.modified.length + folderChanges.deleted.length;

    // Общее количество изменений
    const totalChanges = materialChanges + folderChangesCount;

    if (totalChanges === 0) {
        alert('Нет изменений для применения.\n\nБаза данных уже актуальна!');
        closeModal('import');
        return;
    }

    // Формируем сообщение подтверждения
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

    // Предупреждение об удалениях
    if (deleted.length > 0 || folderChanges.deleted.length > 0) {
        confirmMsg += `⚠️ ВНИМАНИЕ: Некоторые записи будут удалены!\n\n`;
    }

    confirmMsg += `Продолжить?`;

    if (!confirm(confirmMsg)) return;

    showImportStep('progress');
    els.importProgress.style.width = '0%';
    els.importStatusText.innerText = 'Применение изменений...';

    try {
        // 1. Сначала удаляем записи (если есть)
        if (deleted.length > 0) {
            els.importStatusText.innerText = `Удаление ${deleted.length} записей...`;

            const codesToDelete = deleted.map(r => r.code);
            const batchSize = 100;

            for (let i = 0; i < codesToDelete.length; i += batchSize) {
                const batch = codesToDelete.slice(i, i + batchSize);

                const res = await fetch('/delete_batch_records', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        database: state.activeCollection,
                        codes: batch
                    })
                });

                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || 'Ошибка удаления записей');
                }

                const progress = ((i + batch.length) / codesToDelete.length) * 20;
                els.importProgress.style.width = `${progress}%`;
            }
        }

        els.importProgress.style.width = '20%';

        // 2. Добавление + обновление через /admin/import (с генерацией path_level_N)
        // Получаем колонки иерархии из текущего маппинга
        const hierarchyCols = getOrderedSelection('hierarchy');

        const recordsToUpsert = [
            // Добавленные записи - берём hierarchy из исходных данных
            ...added.map(r => ({
                code: r.code,
                description: r.description,
                // Если есть отдельная иерархия - передаём её
                hierarchy: hierarchyCols.length > 0 ? r.hierarchy : undefined,
                meta: r.meta || {}
            })),
            // Изменённые записи - используем новое описание
            ...modified.map(r => ({
                code: r.code,
                description: r.newDescription,
                // Иерархия из исходных данных (если была настроена)
                hierarchy: hierarchyCols.length > 0 ? r.hierarchy : undefined,
                meta: {}
            }))
        ];


        // Если есть только изменения папок (нет изменений материалов),
        // нужно запустить полный импорт всех материалов из CSV для пересоздания папок
        const folderOnlyChanges = recordsToUpsert.length === 0 &&
            (folderChanges.added.length > 0 || folderChanges.modified.length > 0 || folderChanges.deleted.length > 0);

        if (folderOnlyChanges) {
            els.importStatusText.innerText = `Обновление папок: загрузка всех материалов...`;

            // Загружаем ВСЕ материалы из текущего маппинга для пересоздания папок
            const allRecords = buildRecordsFromMapping();

            const payload = {
                collection_name: state.activeCollection,
                records: allRecords.map(r => ({
                    code: r.code,
                    description: r.description,
                    hierarchy: hierarchyCols.length > 0 ? r.hierarchy : undefined,
                    meta: r.meta
                })),
                recreate: false,
                // Передаём список папок к удалению (вместо сканирования всей базы)
                folders_to_delete: folderChanges.deleted.map(f => f.full_path)
            };

            const res = await authFetch('/admin/import', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Ошибка импорта записей');
            }

            const json = await res.json();

            els.importStatusText.innerText = 'Пересоздание папок каталога...';
            await pollJobUntilComplete(json.job_id, 20, 95);

        } else if (recordsToUpsert.length > 0) {
            els.importStatusText.innerText = `Загрузка ${recordsToUpsert.length} записей через импорт...`;

            // Используем /admin/import для корректной генерации path_level_N
            const payload = {
                collection_name: state.activeCollection,
                records: recordsToUpsert,
                recreate: false,
                // Передаём список папок к удалению (вместо сканирования всей базы)
                folders_to_delete: folderChanges.deleted.map(f => f.full_path)
            };

            const res = await authFetch('/admin/import', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Ошибка импорта записей');
            }

            const json = await res.json();

            // Опрашиваем статус задачи
            els.importStatusText.innerText = 'Обработка записей...';
            await pollJobUntilComplete(json.job_id, 20, 95);
        }

        els.importProgress.style.width = '95%';

        // 3. Инвалидируем кэш иерархии
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

/**
 * Опрос задачи до завершения (синхронный режим для diff).
 * @param {string} jobId - ID задачи
 * @param {number} progressStart - Начальный прогресс (%)
 * @param {number} progressEnd - Конечный прогресс (%)
 * @returns {Promise<void>}
 */
async function pollJobUntilComplete(jobId, progressStart, progressEnd) {
    return new Promise((resolve, reject) => {
        const interval = setInterval(async () => {
            try {
                const res = await authFetch('/admin/jobs');
                const jobs = await res.json();
                const job = jobs.find(j => j.id === jobId);

                if (job) {
                    // Масштабируем прогресс задачи в заданный диапазон
                    const scaledProgress = progressStart + (job.progress / 100) * (progressEnd - progressStart);
                    els.importProgress.style.width = `${scaledProgress}%`;

                    const statusText = {
                        'pending': 'Ожидание',
                        'processing': 'Обработка',
                        'completed': 'Завершено',
                        'error': 'Ошибка'
                    };

                    els.importStatusText.innerText = `${statusText[job.status] || job.status} (${job.progress}%)`;

                    if (job.status === 'completed') {
                        clearInterval(interval);
                        resolve();
                    } else if (job.status === 'error') {
                        clearInterval(interval);
                        reject(new Error(job.error || 'Ошибка обработки'));
                    } else if (job.status === 'cancelled') {
                        clearInterval(interval);
                        reject(new Error('Задача отменена пользователем'));
                    }
                }
            } catch (e) {
                if (e.message === 'Unauthorized') {
                    clearInterval(interval);
                    reject(e);
                }
            }
        }, 1500);
    });
}

/**
 * Подписка на прогресс задачи через WebSocket.
 * Используется вместо polling — мгновенные обновления, без задержки 1.5с.
 * Автоматически переподключается при разрыве.
 */
function watchJob(jobId) {
    // Очищаем предыдущее подключение если было
    if (state.jobWs) {
        try { state.jobWs.close(); } catch (e) {}
        state.jobWs = null;
    }
    if (state.jobInterval) {
        clearInterval(state.jobInterval);
        state.jobInterval = null;
    }

    els.importStatusText.innerText = 'В очереди...';
    els.importProgress.style.width = '0%';

    // Определяем протокол
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    // ВАЖНО: ключ в localStorage — `adminToken` (camelCase), не `admin_token`
    const token = localStorage.getItem('adminToken') || sessionStorage.getItem('adminToken') || '';
    const url = `${proto}://${location.host}/admin/jobs/${jobId}/ws?token=${encodeURIComponent(token)}`;
    console.log('[watchJob] connecting to', url);

    let ws;
    try {
        ws = new WebSocket(url);
    } catch (e) {
        console.error('[watchJob] WebSocket construction failed:', e);
        pollJob(jobId);  // fallback to polling
        return;
    }
    state.jobWs = ws;

    // Таймаут 60 сек на pending без обновлений
    let lastUpdate = Date.now();
    const watchDog = setInterval(() => {
        if (Date.now() - lastUpdate > 60_000) {
            console.warn('[watchJob] no updates for 60s, fallback to polling');
            try { ws.close(); } catch (e) {}
            state.jobWs = null;
            pollJob(jobId);
            clearInterval(watchDog);
        }
    }, 10_000);

    const statusText = {
        'pending': 'Ожидание',
        'processing': 'Обработка',
        'completed': 'Завершено',
        'error': 'Ошибка',
        'cancelled': 'Отменено'
    };

    ws.onopen = () => {
        console.log('[watchJob] WebSocket open');
        lastUpdate = Date.now();
    };

    ws.onmessage = (ev) => {
        lastUpdate = Date.now();
        let msg;
        try { msg = JSON.parse(ev.data); } catch (e) { return; }
        console.log('[watchJob] update:', msg);
        if (msg.type === 'progress' || msg.type === 'status') {
            const j = msg.data || msg;
            els.importProgress.style.width = `${j.progress || 0}%`;
            const st = j.status || 'pending';
            const detail = j.details ? ` — ${j.details}` : '';
            els.importStatusText.innerText = `${statusText[st] || st} (${j.progress || 0}%)${detail}`;
        } else if (msg.type === 'done') {
            const j = msg.data || msg;
            els.importProgress.style.width = '100%';
            els.importStatusText.innerText = 'Завершено';
            try { ws.close(); } catch (e) {}
            state.jobWs = null;
            clearInterval(watchDog);

            fetch(`/hierarchy/${state.activeCollection}/invalidate`, { method: 'POST' })
                .then(() => console.log('✅ Кэш иерархии очищен'))
                .catch(e => console.warn('⚠️ Не удалось очистить кэш иерархии:', e));

            const result = j.result || {};
            const m = result.materials || 0;
            const f = result.folders || {};
            setTimeout(() => {
                alert(`Импорт завершён!\n\nМатериалов: ${m}\nПапок создано: ${f.created || 0}\nУдалено: ${f.deleted || 0}`);
                closeModal('import');
                loadCollections();
            }, 300);
        } else if (msg.type === 'error') {
            els.importStatusText.innerText = `Ошибка: ${msg.message || 'unknown'}`;
            try { ws.close(); } catch (e) {}
            state.jobWs = null;
            clearInterval(watchDog);
            setTimeout(() => {
                alert(`Ошибка импорта: ${msg.message || 'unknown'}`);
                closeModal('import');
            }, 100);
        } else if (msg.type === 'cancelled') {
            const j = msg.data || msg;
            els.importProgress.style.width = `${j.progress || 0}%`;
            els.importStatusText.innerText = 'Отменено';
            try { ws.close(); } catch (e) {}
            state.jobWs = null;
            clearInterval(watchDog);
            fetch(`/hierarchy/${state.activeCollection}/invalidate`, { method: 'POST' })
                .then(() => console.log('✅ Кэш иерархии очищен после отмены'))
                .catch(e => console.warn('⚠️ Не удалось очистить кэш иерархии:', e));
            setTimeout(() => {
                alert(`Импорт отменён.\n\n${j.details || ''}`);
                closeModal('import');
                loadJobs();
                loadCollections();
            }, 300);
        }
    };

    ws.onerror = (e) => {
        console.warn('[watchJob] WebSocket error, fallback to polling', e);
        try { ws.close(); } catch (e) {}
        state.jobWs = null;
        clearInterval(watchDog);
        pollJob(jobId);
    };

    ws.onclose = (ev) => {
        console.log('[watchJob] WebSocket closed', ev.code, ev.reason);
        state.jobWs = null;
        clearInterval(watchDog);
    };
}

/**
 * Fallback: опрос статуса фоновой задачи (если WebSocket не работает).
 */
async function pollJob(jobId) {
    if (state.jobInterval) clearInterval(state.jobInterval);
    els.importStatusText.innerText = 'В очереди...';
    els.importProgress.style.width = '0%';

    state.jobInterval = setInterval(async () => {
        try {
            const res = await authFetch('/admin/jobs');
            const data = await res.json();
            const jobs = data.jobs || [];
            const job = jobs.find(j => j.id === jobId);

            if (job) {
                els.importProgress.style.width = `${job.progress || 0}%`;
                const statusText = {
                    'pending': 'Ожидание',
                    'processing': 'Обработка',
                    'completed': 'Завершено',
                    'error': 'Ошибка',
                    'cancelled': 'Отменено'
                };
                els.importStatusText.innerText = `${statusText[job.status] || job.status} (${job.progress || 0}%) — ${job.details || ''}`;

                if (job.status === 'completed') {
                    clearInterval(state.jobInterval);
                    state.jobInterval = null;
                    fetch(`/hierarchy/${state.activeCollection}/invalidate`, { method: 'POST' })
                        .then(() => console.log('✅ Кэш иерархии очищен'))
                        .catch(e => console.warn('⚠️ Не удалось очистить кэш иерархии:', e));
                    setTimeout(() => {
                        const m = job.result?.materials || 0;
                        const f = job.result?.folders || {};
                        alert(`Импорт завершён!\n\nМатериалов: ${m}\nПапок создано: ${f.created || 0}`);
                        closeModal('import');
                        loadCollections();
                    }, 500);
                } else if (job.status === 'error') {
                    clearInterval(state.jobInterval);
                    state.jobInterval = null;
                    alert(`Ошибка: ${job.error || 'unknown'}`);
                    closeModal('import');
                } else if (job.status === 'cancelled') {
                    clearInterval(state.jobInterval);
                    state.jobInterval = null;
                    alert('Импорт отменен пользователем');
                    closeModal('import');
                }
            }
        } catch (e) {
            if (e.message === 'Unauthorized') {
                clearInterval(state.jobInterval);
                state.jobInterval = null;
            }
        }
    }, 2000);
}

// === JOBS VIEW ===
async function loadJobs() {
    try {
        const res = await authFetch('/admin/jobs');
        const data = await res.json();
        const jobs = data.jobs || [];  // backend returns {jobs: [...]}

        const statusText = {
            'pending': 'Ожидание',
            'processing': 'Обработка',
            'completed': 'Завершено',
            'error': 'Ошибка',
            'cancelled': 'Отменено'
        };

        els.jobsTableBody.innerHTML = jobs.map(j => {
            const canStop = j.status === 'pending' || j.status === 'processing';
            const createdAt = j.created_at ? new Date(j.created_at).toLocaleString('ru-RU') : '—';
            return `
            <tr>
                <td style="font-family:monospace; font-size:0.8rem">${j.id.slice(0, 8)}...</td>
                <td>${j.type === 'import_batch' ? 'Импорт' : j.type}</td>
                <td><span class="status-badge status-${j.status}">${statusText[j.status] || j.status}</span></td>
                <td>
                    <div class="progress-bar-container" style="width: 100px; height: 6px;">
                        <div class="progress-bar-fill" style="width: ${j.progress || 0}%"></div>
                    </div>
                    <small>${j.progress || 0}% ${j.total ? `/ ${j.total}` : ''}</small>
                </td>
                <td title="${j.details || ''}">${j.details || '—'}</td>
                <td>${createdAt}</td>
                <td>
                    ${canStop ? `<button class="btn btn-danger" style="padding: 4px 8px; font-size: 0.8rem;" onclick="stopJob('${j.id}')" title="Остановить"><i class="fas fa-stop"></i></button>` : ''}
                </td>
            </tr>
        `}).join('');
    } catch (e) {
        if (e.message !== 'Unauthorized') {
            console.error('Failed to load jobs:', e);
        }
    }
}

function startJobPoller() {
    setInterval(() => {
        if (state.currentView === 'jobs') loadJobs();
    }, 3000);
}

/**
 * Остановка задачи
 */
window.stopJob = async (jobId) => {
    if (!confirm('Вы уверены, что хотите остановить эту задачу?')) return;

    try {
        const res = await authFetch(`/admin/jobs/${jobId}/stop`, { method: 'POST' });
        if (res.ok) {
            loadJobs(); // Обновляем список сразу
        } else {
            const err = await res.json();
            alert('Ошибка: ' + (err.detail || 'Не удалось остановить задачу'));
        }
    } catch (e) {
        alert('Ошибка связи с сервером');
    }
};

// === MODAL UTILS ===
function initModals() {
    document.querySelectorAll('.modal-close, .modal-close-btn').forEach(btn => {
        btn.addEventListener('click', function () {
            const modal = this.closest('.modal-overlay');
            modal.classList.remove('active');
        });
    });
}

// === MODAL RESIZE (Ресайз модального окна импорта) ===

/**
 * Инициализация ресайза модального окна импорта.
 * Позволяет изменять ширину окна перетаскиванием за боковые края.
 */
function initModalResize() {
    const modalWindow = document.getElementById('importModalWindow');
    if (!modalWindow) return;

    const resizers = modalWindow.querySelectorAll('.modal-resizer');

    let isResizing = false;
    let startX = 0;
    let startWidth = 0;
    let currentResizer = null;

    // Восстанавливаем сохранённую ширину
    const savedWidth = localStorage.getItem('importModalWidth');
    if (savedWidth) {
        const width = parseInt(savedWidth);
        if (width >= 800 && width <= window.innerWidth * 0.95) {
            modalWindow.style.width = width + 'px';
        }
    }

    resizers.forEach(resizer => {
        resizer.addEventListener('mousedown', (e) => {
            isResizing = true;
            startX = e.clientX;
            startWidth = modalWindow.offsetWidth;
            currentResizer = resizer;
            resizer.classList.add('active');
            document.body.style.cursor = 'ew-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;

        const direction = currentResizer.dataset.direction;
        let delta = e.clientX - startX;

        // Для левого resizer инвертируем дельту и удваиваем (симметрично)
        // Для правого - тоже удваиваем для симметричного изменения
        if (direction === 'left') {
            delta = -delta;
        }

        // Симметричное изменение (умножаем на 2)
        const newWidth = Math.max(800, Math.min(window.innerWidth * 0.95, startWidth + delta * 2));
        modalWindow.style.width = newWidth + 'px';
    });

    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            if (currentResizer) {
                currentResizer.classList.remove('active');
            }
            document.body.style.cursor = '';
            document.body.style.userSelect = '';

            // Сохраняем ширину
            localStorage.setItem('importModalWidth', modalWindow.offsetWidth);
        }
    });
}

function openModal(name) {
    if (els.modals[name]) els.modals[name].classList.add('active');
}

function closeModal(name) {
    if (els.modals[name]) els.modals[name].classList.remove('active');

    // Если закрываем окно импорта - останавливаем поллинг UI
    // (сама задача на сервере продолжится, пока её не отменят)
    if (name === 'import' && state.jobInterval) {
        clearInterval(state.jobInterval);
        state.jobInterval = null;
    }
}
