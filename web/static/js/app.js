/**
 * KSR Matcher - Клиентское приложение для семантического поиска
 * 
 * Основные возможности:
 * - Поиск по векторной базе данных с отображением результатов
 * - Переключение между коллекциями (базами данных)
 * - Тёмная/светлая тема интерфейса
 * - Сбор аналитики (копирование, дизлайки)
 * 
 * @author Alexandr
 * @version 2.0.0
 * @license MIT
 */

document.addEventListener('DOMContentLoaded', function () {
    // === DOM ЭЛЕМЕНТЫ ===
    const queryInput = document.getElementById('query');
    const clearBtn = document.getElementById('clearBtn');
    const searchBtn = document.getElementById('searchBtn');
    const resultsBody = document.getElementById('resultsBody');
    const errorContainer = document.getElementById('errorContainer');
    const statusInfo = document.getElementById('statusInfo');
    const processingInfo = document.getElementById('processingInfo');
    const processingTimeElement = document.getElementById('processingTime');
    const databaseSelect = document.getElementById('databaseSelect');
    const databaseOptions = document.getElementById('databaseOptions');

    // Кастомный dropdown
    const customSelectWrapper = document.getElementById('customSelect');
    const customSelectTrigger = customSelectWrapper.querySelector('.custom-select-trigger');
    const customOptionsContainer = document.getElementById('customOptions');
    const customSelectValue = document.getElementById('customSelectValue');

    // Переключатель темы
    const themeToggle = document.getElementById('themeToggle');
    const themeIcon = themeToggle.querySelector('i');
    const themeText = themeToggle.querySelector('span');

    // === СОСТОЯНИЕ ПРИЛОЖЕНИЯ ===
    /** @type {string} Текущая выбранная база данных */
    let currentDatabase = 'ksr_main';
    /** @type {Array} Список доступных баз данных */
    let databases = [];
    /** @type {string} Текущий поисковый запрос */
    let currentQuery = '';
    /** @type {Array} Результаты последнего поиска */
    let currentResults = [];
    
    // === СОСТОЯНИЕ КАТАЛОГА ===
    /** @type {Object|null} Дерево иерархии категорий */
    let hierarchyTree = null;
    /** @type {Array} Массив выбранных путей для множественной фильтрации */
    let selectedPaths = [];
    /** @type {string|null} Текущий путь фильтрации (для одиночного выбора) */
    let currentFilterPath = null;
    /** @type {number|null} Текущий уровень фильтрации (1, 2, 3...) */
    let currentFilterLevel = null;
    /** @type {boolean} Sidebar свёрнут/развёрнут */
    let sidebarCollapsed = false;
    /** @type {number} Ширина sidebar */
    let sidebarWidth = parseInt(localStorage.getItem('sidebarWidth')) || 500;
    
    // === DOM ЭЛЕМЕНТЫ КАТАЛОГА ===
    const catalogSidebar = document.getElementById('catalogSidebar');
    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebarResizer = document.getElementById('sidebarResizer');
    const hierarchyTreeEl = document.getElementById('hierarchyTree');
    const totalCategoriesEl = document.getElementById('totalCategories');
    const totalItemsEl = document.getElementById('totalItems');
    const appLayout = document.getElementById('appLayout');
    const multiSelectHint = document.getElementById('multiSelectHint');
    const selectedCountEl = document.getElementById('selectedCount');
    const clearSelectionBtn = document.getElementById('clearSelectionBtn');
    
    // === DOM ЭЛЕМЕНТЫ ПОИСКА ПО КАТАЛОГУ ===
    const catalogSearchInput = document.getElementById('catalogSearchInput');
    const catalogSearchClear = document.getElementById('catalogSearchClear');
    const catalogSearchResults = document.getElementById('catalogSearchResults');
    const filterIndicator = document.getElementById('filterIndicator');
    
    // === DOM ЭЛЕМЕНТЫ STICKY BREADCRUMBS ===
    const sidebarContent = document.getElementById('sidebarContent');
    const stickyBreadcrumbs = document.getElementById('stickyBreadcrumbs');
    
    /** @type {number|null} Таймер debounce для поиска по каталогу */
    let catalogSearchDebounce = null;
    
    /** @type {string|null} Последний показанный sticky path (для гистерезиса) */
    let lastStickyPath = null;
    
    /** @type {number} Порог гистерезиса для предотвращения мерцания sticky header */
    const STICKY_HYSTERESIS = 20;
    
    // === LONG PRESS ДЛЯ МОБИЛЬНЫХ УСТРОЙСТВ ===
    /** @type {number|null} Таймер для long press */
    let longPressTimer = null;
    
    /** @type {boolean} Флаг что long press сработал */
    let longPressTriggered = false;
    
    /** @type {number} Начальная X координата касания */
    let touchStartX = 0;
    
    /** @type {number} Начальная Y координата касания */
    let touchStartY = 0;
    
    /** @type {number} Время в мс для срабатывания long press */
    const LONG_PRESS_DURATION = 500;
    
    /** @type {number} Максимальное смещение пальца для отмены long press */
    const LONG_PRESS_MOVE_THRESHOLD = 10;

    queryInput.focus();
    loadAvailableDatabases();
    initTheme();
    initCatalogSidebar();

    // --- THEME TOGGLE LOGIC (ТЁМНАЯ ПО УМОЛЧАНИЮ) ---

    /**
     * Инициализация темы при загрузке страницы.
     * Читает сохраненную тему из localStorage или устанавливает 'dark' по умолчанию.
     */
    function initTheme() {
        const savedTheme = localStorage.getItem('theme') || 'dark'; // ИЗМЕНЕНО: по умолчанию dark
        setTheme(savedTheme);
    }

    /**
     * Применение темы интерфейса.
     * Обновляет CSS-переменные через атрибут data-theme и меняет иконку кнопки.
     * @param {string} theme - 'dark' или 'light'
     */
    function setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);

        if (theme === 'dark') {
            themeIcon.classList.remove('fa-moon');
            themeIcon.classList.add('fa-sun');
            if (themeText) themeText.textContent = 'Светлая тема';
        } else {
            themeIcon.classList.remove('fa-sun');
            themeIcon.classList.add('fa-moon');
            if (themeText) themeText.textContent = 'Тёмная тема';
        }
    }

    themeToggle.addEventListener('click', () => {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        setTheme(newTheme);
    });

    // --- CUSTOM DROPDOWN LOGIC ---

    customSelectTrigger.addEventListener('click', (e) => {
        e.stopPropagation();
        customSelectWrapper.classList.toggle('open');
    });

    document.addEventListener('click', (e) => {
        if (!customSelectWrapper.contains(e.target)) {
            customSelectWrapper.classList.remove('open');
        }
    });

    /**
     * Инициализация кастомного выпадающего списка для выбора базы данных.
     * Преобразует стандартный <select> в стилизованный div-компонент.
     */
    function initCustomSelect() {
        customOptionsContainer.innerHTML = '';

        Array.from(databaseSelect.options).forEach(option => {
            const div = document.createElement('div');
            div.classList.add('custom-option');
            div.textContent = option.textContent;
            div.dataset.value = option.value;

            if (option.selected) {
                div.classList.add('selected');
                customSelectValue.textContent = option.textContent;
            }

            div.addEventListener('click', function () {
                customSelectWrapper.querySelectorAll('.custom-option').forEach(el => el.classList.remove('selected'));
                this.classList.add('selected');
                customSelectValue.textContent = this.textContent;
                customSelectWrapper.classList.remove('open');

                databaseSelect.value = this.dataset.value;
                setCurrentDatabase(this.dataset.value);
            });

            customOptionsContainer.appendChild(div);
        });
    }

    clearBtn.addEventListener('click', () => {
        queryInput.value = '';
        queryInput.focus();
        clearResults();
        processingInfo.textContent = 'Ожидание запроса...';
        processingTimeElement.textContent = '0.00s';
        currentResults = [];
        
        // Также сбрасываем фильтр по категории
        clearFilter();
    });

    searchBtn.addEventListener('click', performSearch);
    queryInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            performSearch();
        }
    });

    // Event Delegation
    document.addEventListener('click', function (e) {
        if (e.target.closest('.copy-btn')) {
            const btn = e.target.closest('.copy-btn');
            const row = btn.closest('tr');
            const code = row.querySelector('.code-text').textContent;
            const rank = parseInt(row.dataset.rank);

            navigator.clipboard.writeText(code).then(() => {
                const originalHtml = btn.innerHTML;
                btn.innerHTML = '<i class="fas fa-check" style="color:var(--success)"></i>';
                setTimeout(() => btn.innerHTML = originalHtml, 1500);

                if (currentQuery && currentResults.length > 0) {
                    const result = currentResults.find(r => r.rank === rank);
                    if (result) {
                        sendAnalytics('copy', {
                            code: result.code,
                            rank: result.rank,
                            description: result.description,
                            reranker_score: result.reranker_score,
                            cosine_similarity: result.cosine_similarity
                        });
                    }
                }
            });
        }

        if (e.target.closest('.dislike-btn')) {
            const btn = e.target.closest('.dislike-btn');
            const row = btn.closest('tr');
            const rank = parseInt(row.dataset.rank);

            btn.innerHTML = '<i class="fas fa-thumbs-down" style="color:var(--danger)"></i>';

            if (currentQuery && currentResults.length > 0) {
                const result = currentResults.find(r => r.rank === rank);
                if (result) {
                    sendAnalytics('dislike', {
                        code: result.code,
                        rank: result.rank,
                        description: result.description,
                        reranker_score: result.reranker_score,
                        cosine_similarity: result.cosine_similarity
                    });
                }
            }
        }

        if (e.target.closest('.db-card')) {
            const dbName = e.target.closest('.db-card').dataset.name;
            const option = Array.from(customOptionsContainer.children).find(div => div.dataset.value === dbName);
            if (option) option.click();
        }
        
        // Обработчик клика по пути категорий в результатах поиска
        // Открывает каталог и навигирует к выбранной категории
        if (e.target.closest('.result-category-path')) {
            const pathEl = e.target.closest('.result-category-path');
            const categoryPath = pathEl.dataset.categoryPath;
            
            if (categoryPath) {
                navigateToCategoryInCatalog(categoryPath);
            }
        }
    });

    /**
     * Управление состоянием загрузки UI.
     * Блокирует кнопку поиска и показывает индикатор загрузки.
     * @param {boolean} loading - true для показа состояния загрузки
     */
    function setLoading(loading) {
        searchBtn.disabled = loading;
        if (loading) {
            searchBtn.innerHTML = '<div class="loading-spinner"></div> Ищем...';
            statusInfo.textContent = 'Поиск...';
            statusInfo.style.color = 'var(--primary)';
            processingInfo.textContent = 'Нейросеть обрабатывает запрос...';
        } else {
            searchBtn.innerHTML = '<i class="fas fa-bolt"></i> Найти';
        }
    }

    /**
     * Очистка таблицы результатов и сброс UI в исходное состояние.
     */
    function clearResults() {
        resultsBody.innerHTML = `
                    <tr><td colspan="6" style="text-align: center; padding: 60px 20px; color: var(--text-secondary);">
                    Результаты очищены</td></tr>`;
        errorContainer.classList.add('hidden');
        statusInfo.textContent = 'Готов к работе';
        statusInfo.style.color = 'var(--success)';
    }

    /**
     * Создание HTML-разметки для индикатора прогресса (score bar).
     * @param {number} val - Значение от 0 до 1
     * @returns {string} HTML строка с прогресс-баром
     */
    function createScoreBar(val) {
        const pct = Math.min(100, val * 100);
        return `<div class="progress-bg"><div class="progress-fill" style="width:${pct}%"></div></div>`;
    }

    /**
     * Загрузка списка доступных баз данных с сервера.
     * Выполняет GET /databases и инициализирует UI компоненты выбора базы.
     * Пороги (rerank/cosine) и record_count подтягиваются здесь же
     * и обновляются при каждой загрузке/перезагрузке страницы.
     */
    async function loadAvailableDatabases() {
        try {
            const res = await fetch('/databases');
            if (res.ok) {
                const data = await res.json();
                databases = data.databases;
                currentDatabase = data.current_database || 'ksr_main';

                databaseSelect.innerHTML = '';
                databases.forEach(db => {
                    const opt = document.createElement('option');
                    opt.value = db.name;
                    opt.textContent = db.description.split('(')[0];
                    if (db.name === currentDatabase) opt.selected = true;
                    databaseSelect.appendChild(opt);
                });

                renderDbCards();
                initCustomSelect();
                setCurrentDatabase(currentDatabase);
            }
        } catch (e) { console.error(e); }
    }

    /**
     * Отрисовка карточек выбора базы данных под полем ввода.
     * Отображает название, количество записей и дату последнего обновления.
     */
    function renderDbCards() {
        let html = '';
        databases.forEach(db => {
            const active = db.name === currentDatabase ? 'active' : '';
            const dateHtml = db.last_updated 
                ? `<div class="db-card-date">Обновлено: ${db.last_updated}</div>` 
                : '';

            html += `
                        <div class="db-card ${active}" data-name="${db.name}">
                            <div class="db-card-name">${db.description.split('(')[0]}</div>
                            <div class="db-card-desc">${db.record_count.toLocaleString()} записей</div>
                            ${dateHtml}
                        </div>`;
        });
        databaseOptions.innerHTML = html;
    }

    /**
     * Установка активной базы данных.
     * Обновляет UI компоненты и метрики порогов.
     * @param {string} name - Имя коллекции (например, 'ksr_main')
     */
    function setCurrentDatabase(name) {
        currentDatabase = name;
        databaseSelect.value = name;

        renderDbCards();

        if (customOptionsContainer.children.length > 0) {
            const selectedOption = Array.from(customOptionsContainer.children).find(div => div.dataset.value === name);
            if (selectedOption) {
                customSelectValue.textContent = selectedOption.textContent;
                Array.from(customOptionsContainer.children).forEach(el => el.classList.remove('selected'));
                selectedOption.classList.add('selected');
            }
        }

        const db = databases.find(d => d.name === name);
        if (db) {
            // Phase 4: в шапке показываем adaptive threshold (а не старый hard rerank).
            // Cosine оставлен как fallback-cosine; rerank_threshold больше не используется.
            const p4 = db.phase4 || {};
            const confidentEl = document.getElementById('confidentMin');
            const uncertainEl = document.getElementById('uncertainMin');
            const cosineEl = document.getElementById('cosineThreshold');
            if (confidentEl) confidentEl.textContent = (p4.adaptive_confident_min ?? 0.5).toFixed(2);
            if (uncertainEl) uncertainEl.textContent = (p4.adaptive_uncertain_min ?? 0.15).toFixed(2);
            if (cosineEl) cosineEl.textContent = (p4.fallback_cosine_min ?? 0.30).toFixed(2);
            processingInfo.textContent = `Выбрана база: ${db.description.split('(')[0]}`;
            
            // Обновляем количество записей в sidebar из данных базы
            if (totalItemsEl) {
                totalItemsEl.textContent = db.record_count?.toLocaleString() || 0;
            }
        }
        
        // ИСПРАВЛЕНИЕ: Загрузка иерархии в отложенном режиме для предотвращения блокировки UI
        // setTimeout с 0 ms переносит выполнение в следующий цикл event loop,
        // позволяя основному приложению (GPU-поиск) работать без ожидания загрузки каталога (CPU)
        setTimeout(() => {
            loadHierarchy(name);
        }, 0);
    }

    /**
     * Выполнение поискового запроса.
     * Отправляет POST /match и обрабатывает результат.
     * Управляет состоянием загрузки UI (спиннеры, блокировка кнопок).
     * 
     * Если выбраны категории через Ctrl+клик (selectedPaths),
     * то поиск выполняется внутри всех выбранных категорий (OR логика).
     */
    async function performSearch() {
        const q = queryInput.value.trim();
        if (!q) return;

        setLoading(true);
        errorContainer.classList.add('hidden');

        try {
            // Формируем тело запроса с учётом фильтра по категориям
            const requestBody = { 
                text: q, 
                database: currentDatabase 
            };
            
            // Приоритет: множественный фильтр (selectedPaths) > одиночный (currentFilterPath)
            if (selectedPaths && selectedPaths.length > 0) {
                // Множественный фильтр - передаём массив путей
                requestBody.filter_paths = selectedPaths.map(p => ({
                    path: p.path,
                    level: p.level
                }));
                console.log(`🔍 Поиск с множественным фильтром (${selectedPaths.length} категорий):`, requestBody.filter_paths);
            } else if (currentFilterPath && currentFilterLevel) {
                // Одиночный фильтр (обратная совместимость)
                requestBody.filter_path = currentFilterPath;
                requestBody.filter_level = currentFilterLevel;
                console.log(`🔍 Поиск с фильтром: level=${currentFilterLevel}, path="${currentFilterPath}"`);
            }
            
            const res = await fetch('/match', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody)
            });
            if (!res.ok) throw new Error("Ошибка соединения с сервером");

            const data = await res.json();
            displayResults(data);
        } catch (e) {
            errorContainer.textContent = e.message;
            errorContainer.classList.remove('hidden');
            statusInfo.textContent = 'Ошибка';
            statusInfo.style.color = 'var(--danger)';
            processingInfo.textContent = 'Произошла ошибка при поиске';
        } finally {
            setLoading(false);
        }
    }

    /**
     * Отображение результатов поиска в таблице.
     * Генерирует HTML-разметку для каждого кандидата и вставляет в DOM.
     * @param {Object} data - Ответ от сервера (/match)
     * @param {string} data.query - Исходный запрос
     * @param {Array} data.candidates - Массив результатов
     * @param {number} data.processing_time - Время обработки (сек)
     */
    function displayResults(data) {
        currentQuery = data.query;
        currentResults = data.candidates;
        processingTimeElement.textContent = data.processing_time.toFixed(2) + 's';
        statusInfo.textContent = `Найдено: ${data.candidates.length}`;
        statusInfo.style.color = 'var(--success)';

        const dbName = databases.find(d => d.name === currentDatabase)?.description.split('(')[0] || currentDatabase;
        
        // Формируем сообщение с учётом фильтра
        let infoText = `Поиск завершен по базе "${dbName}"`;
        if (currentFilterPath) {
            // Показываем только последний сегмент пути для краткости
            const lastSegment = currentFilterPath.split(' → ').pop();
            infoText += ` в категории "${lastSegment}"`;
        }
        processingInfo.textContent = infoText;

        if (data.candidates.length === 0) {
            resultsBody.innerHTML = `
                <tr><td colspan="6" style="text-align: center; padding: 40px 20px; color: var(--text-secondary);">
                    <i class="fas fa-search" style="font-size: 2rem; margin-bottom: 15px; display: block; opacity: 0.5"></i>
                    Ничего не найдено по вашему запросу.<br>Попробуйте переформулировать или изменить параметры поиска.
                </td></tr>`;
            statusInfo.textContent = 'Ничего не найдено';
            statusInfo.style.color = 'var(--warning)';
            return;
        }

        let html = '';
        data.candidates.forEach(c => {
            const isTop = c.rank === 1;
            
            // Определяем название материала и путь категорий
            // material_name - название без категорий, category_path - путь категорий
            // Fallback на description если material_name не пришёл (старые данные)
            const materialName = c.material_name || c.description;
            const categoryPath = c.category_path || '';
            
            // Заменяем стрелочки "→" на слэши "/" для более чёткого отображения
            const categoryPathDisplay = categoryPath ? categoryPath.replace(/ → /g, ' / ') : '';
            
            // Формируем HTML для пути категорий (кликабельный, с иконкой папки)
            // data-category-path хранит оригинальный путь со стрелками для навигации в каталоге
            const categoryHtml = categoryPath 
                ? `<div class="result-category-path" data-category-path="${escapeHtml(categoryPath)}" title="Перейти в каталог: ${escapeHtml(categoryPath)}">
                       <i class="fas fa-folder"></i>
                       <span>${escapeHtml(categoryPathDisplay)}</span>
                   </div>` 
                : '';
            
            html += `
                        <tr data-rank="${c.rank}">
                            <td style="font-weight:bold; color:${isTop ? 'var(--success)' : 'var(--text-secondary)'}">${c.rank}</td>
                            <td>
                                <span class="code-text">${c.code}</span>
                            </td>
                            <td class="copy-cell">
                                <button class="copy-btn" title="Копировать">
                                    <i class="fas fa-copy"></i>
                                </button>
                            </td>
                            <td class="description-cell">
                                <div class="result-material-name">${escapeHtml(materialName)}</div>
                                ${categoryHtml}
                            </td>
                            <td class="copy-cell">
                                <button class="dislike-btn" data-rank="${c.rank}">
                                    <i class="far fa-thumbs-down"></i>
                                </button>
                            </td>
                            <td>
                                <div class="score-wrapper">
                                    <span class="score-label">Rerank: ${c.reranker_score.toFixed(4)}</span>
                                    ${createScoreBar(c.reranker_score)}
                                </div>
                                <div class="score-wrapper">
                                    <span class="score-label">Cosine: ${c.cosine_similarity.toFixed(4)}</span>
                                    ${createScoreBar(c.cosine_similarity)}
                                </div>
                            </td>
                        </tr>
                    `;
        });
        resultsBody.innerHTML = html;
    }

    /**
     * Отправка аналитических событий на сервер.
     * Используется для трекинга качества поиска (копирование = успех, дизлайк = неудача).
     * @param {string} type - Тип события ('copy' или 'dislike').
     * @param {object} payload - Данные о выбранном результате.
     */
    function sendAnalytics(type, payload) {
        if (type === 'copy') {
            const copyData = {
                query: currentQuery,
                selected_code: payload.code,
                position: payload.rank,
                description: payload.description,
                database: currentDatabase,
                reranker_score: payload.reranker_score,
                cosine_similarity: payload.cosine_similarity
            };

            fetch('/feedback/copy', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(copyData)
            })
                .then(res => res.json())
                .then(data => console.log('✅ Copy event записан:', data))
                .catch(e => console.error('❌ Ошибка записи copy event:', e));

        } else if (type === 'dislike') {
            const dislikeData = {
                timestamp: new Date().toISOString(),
                query: currentQuery,
                selected_code: payload.code,
                position: payload.rank,
                description: payload.description,
                database: currentDatabase,
                reranker_score: payload.reranker_score,
                cosine_similarity: payload.cosine_similarity,
                action: 'dislike'
            };

            fetch('/feedback/dislike', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(dislikeData)
            })
                .then(res => res.json())
                .then(data => console.log('✅ Dislike event записан:', data))
                .catch(e => console.error('❌ Ошибка записи dislike event:', e));
        }
    }

    // ============================================
    // ИЕРАРХИЧЕСКИЙ КАТАЛОГ - ФУНКЦИИ
    // ============================================

    /**
     * Инициализация sidebar каталога.
     * Настраивает обработчики событий и загружает начальные данные.
     */
    function initCatalogSidebar() {
        if (!catalogSidebar || !sidebarToggle) {
            console.warn('⚠️ Элементы sidebar не найдены');
            return;
        }
        
        // Обработчик сворачивания/разворачивания sidebar
        sidebarToggle.addEventListener('click', toggleSidebar);
        
        // Инициализация resizer для изменения ширины
        initSidebarResizer();
        
        // Инициализация sticky header для категорий
        initStickyCategoryHeader();
        
        // Обработчик сброса множественного выбора
        if (clearSelectionBtn) {
            clearSelectionBtn.addEventListener('click', clearAllSelections);
        }
        
        // Обработчик кнопки "Свернуть всё"
        const collapseAllBtn = document.getElementById('collapseAllBtn');
        if (collapseAllBtn) {
            collapseAllBtn.addEventListener('click', collapseAllTreeNodes);
        }
        
        // Обработчик кнопки "Обновить каталог"
        const refreshCatalogBtn = document.getElementById('refreshCatalogBtn');
        if (refreshCatalogBtn) {
            refreshCatalogBtn.addEventListener('click', refreshCatalog);
        }

        // Восстановление состояния sidebar из localStorage
        const savedState = localStorage.getItem('catalogSidebarCollapsed');
        if (savedState === 'true') {
            sidebarCollapsed = true;
            catalogSidebar.classList.add('collapsed');
            appLayout.classList.remove('sidebar-open');
            appLayout.classList.add('sidebar-collapsed');
            updateToggleButton();
        } else {
            // Применяем сохранённую ширину
            applySidebarWidth();
        }
    }
    
    /**
     * Инициализация sticky breadcrumbs для отображения иерархии категорий при скролле.
     * Показывает многоуровневые закреплённые строки с названиями раскрытых категорий,
     * когда их заголовки "уходят" за верхнюю границу при прокрутке.
     * Использует requestAnimationFrame и гистерезис для предотвращения мерцания.
     */
    function initStickyCategoryHeader() {
        if (!sidebarContent || !stickyBreadcrumbs) {
            console.warn('⚠️ Элементы sticky breadcrumbs не найдены');
            return;
        }
        
        // Флаг для requestAnimationFrame (предотвращает множественные вызовы)
        let rafPending = false;
        
        sidebarContent.addEventListener('scroll', () => {
            // Используем requestAnimationFrame для плавности и производительности
            if (rafPending) return;
            
            rafPending = true;
            requestAnimationFrame(() => {
                rafPending = false;
                updateStickyCategoryHeader();
            });
        });
    }
    
    /**
     * Обновление sticky breadcrumbs на основе текущей позиции скролла.
     * Находит все раскрытые категории, чьи заголовки "ушли" за верхнюю границу,
     * и показывает их в виде многоуровневых закреплённых строк.
     * Использует гистерезис для предотвращения мерцания на границе.
     */
    function updateStickyCategoryHeader() {
        if (!sidebarContent || !stickyBreadcrumbs) return;
        
        // Получаем позицию верхней границы видимой области (относительно контейнера)
        const containerRect = sidebarContent.getBoundingClientRect();
        const containerTop = containerRect.top;
        
        // Высота sticky breadcrumbs (для учёта отступа)
        const stickyHeight = stickyBreadcrumbs.classList.contains('hidden') ? 0 : stickyBreadcrumbs.offsetHeight;
        
        // Порог: считаем что категория "ушла" если её верх выше этой линии
        const baseThreshold = containerTop + stickyHeight + 10;
        
        // Ищем все раскрытые категории (у которых есть expanded children)
        const allExpandedNodes = sidebarContent.querySelectorAll('.tree-node > .tree-children.expanded');
        
        // Собираем все категории, которые "ушли" за верх, по уровням
        const visibleCategories = [];
        
        allExpandedNodes.forEach(childrenContainer => {
            // Получаем родительский узел и его заголовок
            const parentNode = childrenContainer.closest('.tree-node');
            const header = parentNode.querySelector(':scope > .tree-node-header');
            
            if (!header) return;
            
            // ВАЖНО: Проверяем что категория действительно видима
            if (!isCategoryVisible(parentNode)) {
                return;
            }
            
            const headerRect = header.getBoundingClientRect();
            const level = parseInt(header.dataset.level) || 0;
            const path = header.dataset.path || '';
            const name = header.querySelector('.tree-node-name')?.textContent || '';
            
            // Проверяем: заголовок "ушёл" за верхнюю границу?
            const childrenRect = childrenContainer.getBoundingClientRect();
            
            // Гистерезис для текущих sticky категорий
            const isCurrentlySticky = lastStickyPath && lastStickyPath.includes(path);
            const hysteresisOffset = isCurrentlySticky ? STICKY_HYSTERESIS : 0;
            const threshold = baseThreshold - hysteresisOffset;
            
            if (headerRect.top < threshold && childrenRect.bottom > (baseThreshold + STICKY_HYSTERESIS)) {
                visibleCategories.push({ level, path, name });
            }
        });
        
        // Сортируем по уровню для правильного порядка отображения
        visibleCategories.sort((a, b) => a.level - b.level);
        
        // Формируем ключ для сравнения (все пути объединены)
        const newStickyKey = visibleCategories.map(c => c.path).join('|||');
        
        // Обновляем breadcrumbs только если изменился состав
        if (visibleCategories.length > 0) {
            if (lastStickyPath !== newStickyKey) {
                // Строим HTML для breadcrumbs
                const html = visibleCategories.map(cat => `
                    <div class="sticky-breadcrumb-item" data-level="${cat.level}" data-path="${escapeHtml(cat.path)}">
                        <i class="fas fa-folder"></i>
                        <span title="${escapeHtml(cat.path)}">${escapeHtml(cat.name)}</span>
                    </div>
                `).join('');
                
                stickyBreadcrumbs.innerHTML = html;
                lastStickyPath = newStickyKey;
            }
            stickyBreadcrumbs.classList.remove('hidden');
        } else {
            // Скрываем breadcrumbs - все категории видны или ничего не раскрыто
            if (lastStickyPath !== null) {
                stickyBreadcrumbs.classList.add('hidden');
                stickyBreadcrumbs.innerHTML = '';
                lastStickyPath = null;
            }
        }
    }
    
    /**
     * Проверяет, что категория действительно видима в дереве.
     * Категория считается видимой если все её родительские контейнеры раскрыты.
     * @param {HTMLElement} node - Узел дерева (.tree-node)
     * @returns {boolean} true если категория видима
     */
    function isCategoryVisible(node) {
        // Поднимаемся по дереву и проверяем, что все родительские .tree-children имеют класс expanded
        let current = node.parentElement;
        
        while (current && !current.classList.contains('tree-view')) {
            // Если это контейнер детей и он свёрнут - категория не видима
            if (current.classList.contains('tree-children') && current.classList.contains('collapsed')) {
                return false;
            }
            current = current.parentElement;
        }
        
        return true;
    }
    
    /**
     * Инициализация resizer для изменения ширины sidebar.
     */
    function initSidebarResizer() {
        if (!sidebarResizer) return;
        
        let isResizing = false;
        let startX = 0;
        let startWidth = 0;
        
        sidebarResizer.addEventListener('mousedown', (e) => {
            isResizing = true;
            startX = e.clientX;
            startWidth = catalogSidebar.offsetWidth;
            sidebarResizer.classList.add('active');
            document.body.style.cursor = 'ew-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });
        
        document.addEventListener('mousemove', (e) => {
            if (!isResizing) return;
            
            const delta = e.clientX - startX;
            const newWidth = Math.max(350, Math.min(800, startWidth + delta));
            
            sidebarWidth = newWidth;
            applySidebarWidth();
        });
        
        document.addEventListener('mouseup', () => {
            if (isResizing) {
                isResizing = false;
                sidebarResizer.classList.remove('active');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
                localStorage.setItem('sidebarWidth', sidebarWidth);
            }
        });
    }
    
    /**
     * Применяет ширину sidebar.
     */
    function applySidebarWidth() {
        if (sidebarCollapsed) return;
        catalogSidebar.style.width = sidebarWidth + 'px';
        document.documentElement.style.setProperty('--sidebar-width', sidebarWidth + 'px');
    }
    
    /**
     * Обновляет текст и иконку кнопки toggle.
     */
    function updateToggleButton() {
        const icon = sidebarToggle.querySelector('i');
        const text = sidebarToggle.querySelector('.toggle-text');
        
        if (sidebarCollapsed) {
            icon.classList.remove('fa-angles-left');
            icon.classList.add('fa-angles-right');
            if (text) text.textContent = 'Развернуть';
        } else {
            icon.classList.remove('fa-angles-right');
            icon.classList.add('fa-angles-left');
            if (text) text.textContent = 'Свернуть';
        }
    }

    /**
     * Переключение состояния sidebar (свёрнут/развёрнут).
     */
    function toggleSidebar() {
        sidebarCollapsed = !sidebarCollapsed;
        catalogSidebar.classList.toggle('collapsed', sidebarCollapsed);
        
        if (sidebarCollapsed) {
            appLayout.classList.remove('sidebar-open');
            appLayout.classList.add('sidebar-collapsed');
            catalogSidebar.style.width = '';
        } else {
            appLayout.classList.remove('sidebar-collapsed');
            appLayout.classList.add('sidebar-open');
            applySidebarWidth();
        }
        
        updateToggleButton();
        localStorage.setItem('catalogSidebarCollapsed', sidebarCollapsed);
    }
    
    /**
     * Сворачивание всех развёрнутых узлов дерева каталога.
     * Закрывает все раскрытые категории одним кликом.
     */
    function collapseAllTreeNodes() {
        // Находим все развёрнутые дочерние контейнеры
        const expandedChildren = document.querySelectorAll('.tree-children.expanded');
        
        expandedChildren.forEach(children => {
            // Сворачиваем контейнер
            children.classList.remove('expanded');
            children.classList.add('collapsed');
            
            // Убираем состояние expanded у иконки родителя
            const parentNode = children.closest('.tree-node');
            if (parentNode) {
                const expandIcon = parentNode.querySelector(':scope > .tree-node-header .tree-node-expand');
                if (expandIcon) {
                    expandIcon.classList.remove('expanded');
                }
            }
        });
        
        // Скрываем sticky breadcrumbs так как все категории свёрнуты
        if (stickyBreadcrumbs) {
            stickyBreadcrumbs.classList.add('hidden');
            stickyBreadcrumbs.innerHTML = '';
            lastStickyPath = null;
        }
        
        console.log(`📁 Свёрнуто ${expandedChildren.length} категорий`);
    }
    
    /**
     * Обновление каталога - инвалидирует серверный кэш и перезагружает дерево.
     * Вызывается по клику на кнопку "Обновить" в footer каталога.
     */
    async function refreshCatalog() {
        const refreshBtn = document.getElementById('refreshCatalogBtn');
        const icon = refreshBtn ? refreshBtn.querySelector('i') : null;
        
        // Показываем анимацию вращения
        if (icon) {
            icon.classList.add('fa-spin');
        }
        if (refreshBtn) {
            refreshBtn.disabled = true;
        }
        
        try {
            // 1. Инвалидируем серверный кэш
            console.log(`🔄 Инвалидация кэша для ${currentDatabase}...`);
            const res = await fetch(`/hierarchy/${currentDatabase}/invalidate`, { method: 'POST' });
            
            if (!res.ok) {
                throw new Error(`HTTP ${res.status}`);
            }
            
            console.log('✅ Серверный кэш очищен');
            
            // 2. Очищаем клиентский кэш загруженных путей
            loadedPaths.clear();
            
            // 3. Сворачиваем все раскрытые узлы
            collapseAllTreeNodes();
            
            // 4. Перезагружаем иерархию
            await loadHierarchy(currentDatabase);
            
            console.log('✅ Каталог обновлён');
            
        } catch (e) {
            console.error('❌ Ошибка обновления каталога:', e);
            alert('Ошибка обновления каталога: ' + e.message);
        } finally {
            // Убираем анимацию вращения
            if (icon) {
                icon.classList.remove('fa-spin');
            }
            if (refreshBtn) {
                refreshBtn.disabled = false;
            }
        }
    }

    /** @type {Set} Кэш загруженных путей (для ленивой загрузки) */
    const loadedPaths = new Set();
    
    /** @type {boolean} Флаг загрузки иерархии (предотвращает повторные вызовы) */
    let isHierarchyLoading = false;
    
    /**
     * Загрузка иерархии категорий с сервера (ЛЕНИВАЯ ЗАГРУЗКА).
     * Загружает только верхний уровень, остальное - при раскрытии.
     * Полностью асинхронна - не блокирует основной поток UI и GPU-поиск.
     * @param {string} databaseName - Имя коллекции
     */
    async function loadHierarchy(databaseName) {
        if (!hierarchyTreeEl) return;
        
        // Предотвращаем повторный запуск если загрузка уже идёт
        if (isHierarchyLoading) {
            console.log('⏳ Загрузка иерархии уже выполняется, пропускаем...');
            return;
        }
        
        isHierarchyLoading = true;
        
        // Очищаем кэш загруженных путей при смене базы
        loadedPaths.clear();
        
        // Показываем индикатор загрузки
        hierarchyTreeEl.innerHTML = `
            <div class="tree-loading">
                <i class="fas fa-spinner fa-spin"></i>
                <div>Загрузка каталога...</div>
            </div>
        `;
        
        try {
            // Загружаем только верхний уровень (ленивая загрузка)
            const res = await fetch(`/hierarchy/${databaseName}/children?parent_path=&level=1`);
            
            if (!res.ok) {
                throw new Error(`HTTP ${res.status}`);
            }
            
            const data = await res.json();
            
            // Помечаем корень как загруженный
            loadedPaths.add('');
            
            // Обновляем статистику (примерно)
            if (totalCategoriesEl) totalCategoriesEl.textContent = data.total || 0;
            
            // Рендерим только верхний уровень (категории + материалы без категорий)
            renderTreeLazy(data.children || [], data.materials || []);
            
            // Сбрасываем фильтр при смене базы
            clearFilter();
            
            console.log(`✅ Загружено ${data.total} элементов верхнего уровня, cached: ${data.cached}`);
            
        } catch (e) {
            console.error('❌ Ошибка загрузки иерархии:', e);
            hierarchyTreeEl.innerHTML = `
                <div class="tree-empty">
                    <i class="fas fa-exclamation-triangle" style="color: var(--danger);"></i>
                    <div>Не удалось загрузить каталог</div>
                    <div style="font-size: 0.8rem; margin-top: 5px;">${e.message}</div>
                </div>
            `;
        } finally {
            // Сбрасываем флаг загрузки в любом случае
            isHierarchyLoading = false;
        }
    }
    
    /**
     * Загрузка дочерних категорий и материалов при раскрытии.
     * 
     * НОВАЯ ЛОГИКА v2: Поддержка раздельной загрузки категорий и материалов.
     * 
     * @param {string} parentPath - Путь родительской категории
     * @param {HTMLElement} childrenContainer - Контейнер для вставки детей
     */
    async function loadChildren(parentPath, childrenContainer) {
        // Проверяем кэш
        if (loadedPaths.has(parentPath)) {
            return; // Уже загружено
        }
        
        // Показываем индикатор загрузки
        childrenContainer.innerHTML = `
            <div class="tree-loading" style="padding: 15px;">
                <i class="fas fa-spinner fa-spin"></i>
                <span style="margin-left: 8px; font-size: 0.8rem;">Загрузка...</span>
            </div>
        `;
        
        try {
            const res = await fetch(
                `/hierarchy/${currentDatabase}/children?parent_path=${encodeURIComponent(parentPath)}`
            );
            
            if (!res.ok) {
                throw new Error(`HTTP ${res.status}`);
            }
            
            const data = await res.json();
            
            // Помечаем как загруженный
            loadedPaths.add(parentPath);
            
            // Рендерим детей (категории + материалы)
            const hasChildren = (data.children && data.children.length > 0);
            const hasMaterials = (data.materials && data.materials.length > 0);
            
            if (hasChildren || hasMaterials) {
                // Передаём и категории, и материалы в renderTreeNodesLazy
                childrenContainer.innerHTML = renderTreeNodesLazy(data.children || [], data.materials || []);
                // Добавляем обработчики событий для новых узлов
                attachTreeEventHandlersForContainer(childrenContainer);
            } else {
                childrenContainer.innerHTML = '<div class="tree-empty-children" style="padding: 10px; color: var(--text-secondary); font-size: 0.85rem;">Нет элементов</div>';
            }
            
        } catch (e) {
            console.error(`❌ Ошибка загрузки детей для "${parentPath}":`, e);
            childrenContainer.innerHTML = `
                <div style="padding: 10px; color: var(--danger); font-size: 0.8rem;">
                    Ошибка загрузки
                </div>
            `;
        }
    }

    /**
     * Рендеринг дерева категорий (старая версия - полная загрузка).
     * @param {Array} tree - Массив корневых узлов дерева
     */
    function renderTree(tree) {
        if (!hierarchyTreeEl) return;
        
        if (!tree || tree.length === 0) {
            hierarchyTreeEl.innerHTML = `
                <div class="tree-empty">
                    <i class="fas fa-folder-open" style="opacity: 0.5;"></i>
                    <div>Категории не найдены</div>
                    <div style="font-size: 0.8rem; margin-top: 5px;">
                        Возможно, данные ещё не мигрированы
                    </div>
                </div>
            `;
            return;
        }
        
        // Для полной загрузки используем ленивый рендеринг тоже
        hierarchyTreeEl.innerHTML = renderTreeNodesLazy(tree.map(node => ({
            ...node,
            has_children: node.children && node.children.length > 0
        })));
        
        // Добавляем обработчики событий
        attachTreeEventHandlers();
    }
    
    /**
     * Рендеринг дерева с ленивой загрузкой (только верхний уровень).
     * 
     * НОВАЯ ЛОГИКА v2: Поддержка раздельного отображения категорий и материалов.
     * 
     * @param {Array} nodes - Массив узлов верхнего уровня (категории)
     * @param {Array} materials - Массив материалов верхнего уровня (опционально)
     */
    function renderTreeLazy(nodes, materials = []) {
        if (!hierarchyTreeEl) return;
        
        const hasNodes = nodes && nodes.length > 0;
        const hasMaterials = materials && materials.length > 0;
        
        if (!hasNodes && !hasMaterials) {
            hierarchyTreeEl.innerHTML = `
                <div class="tree-empty">
                    <i class="fas fa-folder-open" style="opacity: 0.5;"></i>
                    <div>Категории не найдены</div>
                </div>
            `;
            return;
        }
        
        hierarchyTreeEl.innerHTML = renderTreeNodesLazy(nodes, materials);
        
        // Добавляем обработчики событий
        attachTreeEventHandlers();
    }
    
    /**
     * Рендеринг узлов для ленивой загрузки.
     * 
     * НОВАЯ ЛОГИКА v2: Поддержка раздельного отображения категорий и материалов.
     * - is_category: true - это папка (категория)
     * - is_material: true - это материал (листовой элемент)
     * - has_children или has_materials - есть дочерние элементы для ленивой загрузки
     * 
     * @param {Array} nodes - Массив узлов (категории)
     * @param {Array} materials - Массив материалов (опционально)
     * @returns {string} HTML-разметка
     */
    function renderTreeNodesLazy(nodes, materials = []) {
        let html = '';
        
        // Рендерим категории (папки)
        if (nodes && nodes.length > 0) {
            for (const node of nodes) {
                // Определяем, есть ли дочерние элементы (категории или материалы)
                const hasChildren = node.has_children || node.has_materials || (node.materials && node.materials.length > 0);
                const isMultiSelected = selectedPaths.some(p => p.path === node.path);
                const isCategory = node.is_category !== false; // По умолчанию true
                
                // Определяем классы
                let headerClasses = 'tree-node-header';
                if (isMultiSelected) headerClasses += ' multi-selected';
                
                // Кнопка копирования (для материалов)
                let copyBtnHtml = '';
                const codeValue = node.code || (node.codes && node.codes.length > 0 ? node.codes[0] : null);
                if (codeValue) {
                    copyBtnHtml = `
                        <button class="tree-node-copy" data-code="${escapeHtml(codeValue)}" title="Копировать ${escapeHtml(codeValue)}">
                            <i class="fas fa-copy"></i>
                        </button>
                    `;
                }
                
                // Иконка: папка для категории, куб для материала
                const iconClass = isCategory ? 
                    (hasChildren ? 'fa-folder' : 'fa-folder-open') : 
                    'fa-cube';
                const iconTypeClass = isCategory ? 'folder' : 'material';
                
                html += `
                    <div class="tree-node ${isCategory ? 'category' : 'material'}" data-path="${escapeHtml(node.path)}" data-level="${node.level || 0}">
                        <div class="${headerClasses}" data-path="${escapeHtml(node.path)}" data-level="${node.level || 0}">
                            <span class="tree-node-expand ${hasChildren ? '' : 'empty'}">
                                <i class="fas fa-chevron-right"></i>
                            </span>
                            <span class="tree-node-icon ${iconTypeClass}">
                                <i class="fas ${iconClass}"></i>
                            </span>
                            <span class="tree-node-name" title="${escapeHtml(node.path || node.name)}">${escapeHtml(node.name)}</span>
                            ${copyBtnHtml}
                            <span class="tree-node-count">${(node.count || 1).toLocaleString()}</span>
                        </div>
                        ${hasChildren ? `
                            <div class="tree-children collapsed" data-parent-path="${escapeHtml(node.path)}">
                                <!-- Дети загружаются лениво при раскрытии -->
                            </div>
                        ` : ''}
                    </div>
                `;
            }
        }
        
        // Рендерим материалы (листовые элементы)
        if (materials && materials.length > 0) {
            for (const material of materials) {
                const codeValue = material.code || '';
                const copyBtnHtml = codeValue ? `
                    <button class="tree-node-copy" data-code="${escapeHtml(codeValue)}" title="Копировать ${escapeHtml(codeValue)}">
                        <i class="fas fa-copy"></i>
                    </button>
                ` : '';
                
                html += `
                    <div class="tree-node material" data-code="${escapeHtml(codeValue)}">
                        <div class="tree-node-header material-item" data-code="${escapeHtml(codeValue)}">
                            <span class="tree-node-expand empty">
                                <i class="fas fa-chevron-right" style="visibility: hidden;"></i>
                            </span>
                            <span class="tree-node-icon material">
                                <i class="fas fa-cube"></i>
                            </span>
                            <span class="tree-node-name" title="${escapeHtml(material.name)}">${escapeHtml(material.name)}</span>
                            ${copyBtnHtml}
                        </div>
                    </div>
                `;
            }
        }
        
        if (!html) {
            return '<div class="tree-empty-children" style="padding: 10px; color: var(--text-secondary); font-size: 0.85rem;">Нет элементов</div>';
        }
        
        return html;
    }
    
    /**
     * Добавление обработчиков для узлов в контейнере.
     * @param {HTMLElement} container - Контейнер с узлами
     */
    function attachTreeEventHandlersForContainer(container) {
        container.querySelectorAll('.tree-node-header').forEach(header => {
            attachSingleNodeHandler(header);
        });
    }
    
    /**
     * Добавление обработчика для одного узла.
     * @param {HTMLElement} header - Заголовок узла
     * 
     * Логика:
     * - Обычный клик: только раскрывает/сворачивает категорию (БЕЗ фильтра)
     * - Ctrl+клик: добавляет/убирает категорию в фильтр
     * - Long press (мобильные): добавляет/убирает категорию в фильтр
     */
    function attachSingleNodeHandler(header) {
        // === ОБРАБОТКА КЛИКОВ (ПК) ===
        header.addEventListener('click', (e) => {
            // Если long press сработал - игнорируем клик
            if (longPressTriggered) {
                longPressTriggered = false;
                e.preventDefault();
                e.stopPropagation();
                return;
            }
            
            const path = header.dataset.path;
            const level = parseInt(header.dataset.level);
            const node = header.closest('.tree-node');
            const children = node.querySelector('.tree-children');
            const expandIcon = header.querySelector('.tree-node-expand');
            
            // Если кликнули на кнопку копирования
            if (e.target.closest('.tree-node-copy')) {
                copyCodeFromTree(e.target.closest('.tree-node-copy'));
                return;
            }
            
            // Если кликнули на иконку раскрытия - только toggle
            if (e.target.closest('.tree-node-expand') && children) {
                toggleTreeNodeLazy(children, expandIcon, path);
                return;
            }
            
            // Ctrl+клик - добавляем/убираем из фильтра (БЕЗ раскрытия)
            if (e.ctrlKey || e.metaKey) {
                toggleMultiSelect(path, level, header);
                return; // Важно: НЕ раскрываем категорию при Ctrl+клик
            }
            
            // Обычный клик (без Ctrl) - только toggle раскрытия, БЕЗ выделения и фильтра
            if (children) {
                toggleTreeNodeLazy(children, expandIcon, path);
            }
        });
        
        // === ОБРАБОТКА LONG PRESS (МОБИЛЬНЫЕ) ===
        header.addEventListener('touchstart', (e) => {
            // Не обрабатываем если нажали на кнопку копирования
            if (e.target.closest('.tree-node-copy')) return;
            
            const touch = e.touches[0];
            touchStartX = touch.clientX;
            touchStartY = touch.clientY;
            longPressTriggered = false;
            
            // Запускаем таймер long press
            longPressTimer = setTimeout(() => {
                const path = header.dataset.path;
                const level = parseInt(header.dataset.level);
                
                // Long press сработал
                longPressTriggered = true;
                
                // Вибрация для обратной связи (если поддерживается)
                if (navigator.vibrate) {
                    navigator.vibrate(50);
                }
                
                // Пробуем добавить/убрать из фильтра
                const wasAlreadySelected = selectedPaths.some(p => p.path === path);
                const success = toggleMultiSelect(path, level, header);
                
                // Показываем toast уведомление только если операция успешна
                if (success) {
                    // Если был выбран - теперь удалён, и наоборот
                    showLongPressToast(!wasAlreadySelected);
                }
                
            }, LONG_PRESS_DURATION);
        }, { passive: true });
        
        header.addEventListener('touchmove', (e) => {
            // Отменяем long press если палец сдвинулся слишком далеко
            if (longPressTimer) {
                const touch = e.touches[0];
                const deltaX = Math.abs(touch.clientX - touchStartX);
                const deltaY = Math.abs(touch.clientY - touchStartY);
                
                if (deltaX > LONG_PRESS_MOVE_THRESHOLD || deltaY > LONG_PRESS_MOVE_THRESHOLD) {
                    clearTimeout(longPressTimer);
                    longPressTimer = null;
                }
            }
        }, { passive: true });
        
        header.addEventListener('touchend', () => {
            // Отменяем таймер если отпустили раньше
            if (longPressTimer) {
                clearTimeout(longPressTimer);
                longPressTimer = null;
            }
        });
        
        header.addEventListener('touchcancel', () => {
            // Отменяем таймер при отмене касания
            if (longPressTimer) {
                clearTimeout(longPressTimer);
                longPressTimer = null;
            }
        });
    }
    
    /**
     * Показывает временное уведомление о результате long press.
     * @param {boolean} added - true если категория добавлена, false если удалена
     */
    function showLongPressToast(added) {
        // Удаляем предыдущий toast если есть
        const existingToast = document.querySelector('.longpress-toast');
        if (existingToast) existingToast.remove();
        
        const toast = document.createElement('div');
        toast.className = 'longpress-toast';
        toast.innerHTML = added 
            ? '<i class="fas fa-check"></i> Добавлено в фильтр' 
            : '<i class="fas fa-times"></i> Удалено из фильтра';
        
        document.body.appendChild(toast);
        
        // Удаляем через 2 секунды
        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => toast.remove(), 300);
        }, 2000);
    }
    
    /**
     * Toggle раскрытия узла с ленивой загрузкой.
     * @param {HTMLElement} children - Контейнер дочерних элементов
     * @param {HTMLElement} expandIcon - Иконка раскрытия
     * @param {string} parentPath - Путь родителя для загрузки детей
     */
    async function toggleTreeNodeLazy(children, expandIcon, parentPath) {
        if (children.classList.contains('collapsed')) {
            // Раскрываем
            children.classList.remove('collapsed');
            children.classList.add('expanded');
            if (expandIcon) expandIcon.classList.add('expanded');
            
            // Загружаем детей если ещё не загружены
            if (!loadedPaths.has(parentPath)) {
                await loadChildren(parentPath, children);
            }
        } else {
            // Сворачиваем
            children.classList.remove('expanded');
            children.classList.add('collapsed');
            if (expandIcon) expandIcon.classList.remove('expanded');
        }
        
        // Обновляем sticky header после раскрытия/сворачивания
        // Используем setTimeout чтобы DOM успел обновиться
        setTimeout(() => {
            updateStickyCategoryHeader();
        }, 100);
    }

    /**
     * Экранирование HTML-символов для безопасного вывода.
     * @param {string} text - Исходный текст
     * @returns {string} Экранированный текст
     */
    function escapeHtml(text) {
        if (!text) return '';
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    /**
     * Добавление обработчиков событий к элементам дерева.
     * Использует ленивую загрузку для дочерних элементов.
     */
    function attachTreeEventHandlers() {
        document.querySelectorAll('.tree-node-header').forEach(header => {
            attachSingleNodeHandler(header);
        });
    }
    
    /**
     * Копирование кода из дерева каталога.
     * @param {HTMLElement} btn - Кнопка копирования
     */
    function copyCodeFromTree(btn) {
        const code = btn.dataset.code;
        if (!code) return;
        
        navigator.clipboard.writeText(code).then(() => {
            btn.classList.add('copied');
            const icon = btn.querySelector('i');
            icon.classList.remove('fa-copy');
            icon.classList.add('fa-check');
            
            setTimeout(() => {
                btn.classList.remove('copied');
                icon.classList.remove('fa-check');
                icon.classList.add('fa-copy');
            }, 1500);
            
            console.log(`📋 Скопирован код: ${code}`);
        }).catch(err => {
            console.error('Ошибка копирования:', err);
        });
    }
    
    /**
     * Переключение множественного выбора категории.
     * Разрешает выбор только папок (категорий), но не листьев (материалов).
     * @param {string} path - Путь категории
     * @param {number} level - Уровень
     * @param {HTMLElement} header - Элемент заголовка узла
     * @returns {boolean} true если выбор успешен
     */
    function toggleMultiSelect(path, level, header) {
        const index = selectedPaths.findIndex(p => p.path === path);
        
        if (index > -1) {
            // Убираем из выбранных
            selectedPaths.splice(index, 1);
            header.classList.remove('multi-selected');
            updateMultiSelectUI();
            return true;
        }
        
        // Проверяем - это папка или лист?
        // Папка имеет .tree-children, лист - нет
        const node = header.closest('.tree-node');
        const hasChildren = node && node.querySelector('.tree-children');
        
        if (!hasChildren) {
            // Это лист (материал) - запрещаем добавление в фильтр
            showCategoryOnlyToast();
            return false;
        }
        
        // Это папка - добавляем в выбранные
        selectedPaths.push({ path, level });
        header.classList.add('multi-selected');
        
        updateMultiSelectUI();
        return true;
    }
    
    /**
     * Показывает уведомление что можно выбрать только категории.
     */
    function showCategoryOnlyToast() {
        // Удаляем предыдущий toast если есть
        const existingToast = document.querySelector('.longpress-toast');
        if (existingToast) existingToast.remove();
        
        const toast = document.createElement('div');
        toast.className = 'longpress-toast toast-warning';
        toast.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Можно выбрать только категории';
        
        document.body.appendChild(toast);
        
        // Удаляем через 2 секунды
        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => toast.remove(), 300);
        }, 2000);
    }
    
    /**
     * Обновление UI множественного выбора.
     * Показывает фильтр и индикатор при наличии выбранных категорий.
     */
    function updateMultiSelectUI() {
        if (selectedPaths.length > 0) {
            multiSelectHint.classList.remove('hidden');
            selectedCountEl.textContent = selectedPaths.length;
            
            // Обновляем статус
            const pathNames = selectedPaths.map(p => p.path.split(' → ').pop()).join(', ');
            processingInfo.textContent = `Фильтр: ${pathNames}`;
            
            // Для поиска используем первый выбранный путь (можно расширить логику)
            currentFilterPath = selectedPaths[0].path;
            currentFilterLevel = selectedPaths[0].level;
            
            // Показываем индикатор фильтра (для свёрнутого sidebar)
            if (filterIndicator) {
                filterIndicator.classList.add('active');
            }
        } else {
            multiSelectHint.classList.add('hidden');
            
            // Скрываем индикатор фильтра
            if (filterIndicator) {
                filterIndicator.classList.remove('active');
            }
            
            // Сбрасываем фильтр если нет выбранных категорий
            currentFilterPath = null;
            currentFilterLevel = null;
            processingInfo.textContent = 'Ожидание запроса...';
        }
    }
    
    /**
     * Сброс всех выбранных категорий.
     */
    function clearAllSelections() {
        selectedPaths = [];
        document.querySelectorAll('.tree-node-header.multi-selected').forEach(h => {
            h.classList.remove('multi-selected');
        });
        updateMultiSelectUI();
    }

    /**
     * Сброс фильтра по категории.
     * Очищает все выбранные категории и обновляет UI.
     */
    function clearFilter() {
        currentFilterPath = null;
        currentFilterLevel = null;
        selectedPaths = [];
        
        // Сбрасываем визуальное состояние (только multi-selected, так как active не используется)
        document.querySelectorAll('.tree-node-header.multi-selected').forEach(h => {
            h.classList.remove('multi-selected');
        });
        
        // Скрываем подсказку множественного выбора
        if (multiSelectHint) {
            multiSelectHint.classList.add('hidden');
        }
        
        // Скрываем индикатор фильтра
        if (filterIndicator) {
            filterIndicator.classList.remove('active');
        }
        
        processingInfo.textContent = 'Ожидание запроса...';
        
        console.log('🔍 Фильтр сброшен');
    }

    // === ГЛОБАЛЬНАЯ ФУНКЦИЯ ДЛЯ СБРОСА ФИЛЬТРА ===
    window.clearCatalogFilter = function() {
        clearFilter();
    };

    // ============================================
    // ПОИСК ПО КАТАЛОГУ КАТЕГОРИЙ
    // ============================================

    /**
     * Инициализация поиска по каталогу.
     * Добавляет обработчики событий для input поиска.
     */
    function initCatalogSearch() {
        if (!catalogSearchInput) return;
        
        // Обработчик ввода текста с debounce
        catalogSearchInput.addEventListener('input', (e) => {
            const query = e.target.value.trim();
            
            // Показываем/скрываем кнопку очистки
            if (catalogSearchClear) {
                catalogSearchClear.classList.toggle('hidden', query.length === 0);
            }
            
            // Debounce поиска
            if (catalogSearchDebounce) {
                clearTimeout(catalogSearchDebounce);
            }
            
            if (query.length >= 2) {
                catalogSearchDebounce = setTimeout(() => {
                    performCatalogSearch(query);
                }, 300);
            } else {
                hideCatalogSearchResults();
            }
        });
        
        // Обработчик кнопки очистки
        if (catalogSearchClear) {
            catalogSearchClear.addEventListener('click', () => {
                catalogSearchInput.value = '';
                catalogSearchClear.classList.add('hidden');
                hideCatalogSearchResults();
                catalogSearchInput.focus();
            });
        }
        
        // Скрытие результатов при клике вне
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.catalog-search')) {
                hideCatalogSearchResults();
            }
        });
        
        // Показ результатов при фокусе если есть текст
        catalogSearchInput.addEventListener('focus', () => {
            const query = catalogSearchInput.value.trim();
            if (query.length >= 2 && catalogSearchResults.innerHTML) {
                catalogSearchResults.classList.remove('hidden');
            }
        });
    }

    /**
     * Выполнение семантического поиска по каталогу категорий.
     * @param {string} query - Текст запроса
     */
    async function performCatalogSearch(query) {
        if (!catalogSearchResults) return;
        
        // Показываем индикатор загрузки
        catalogSearchResults.classList.remove('hidden');
        catalogSearchResults.classList.add('loading');
        catalogSearchResults.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Поиск категорий...';
        
        try {
            const res = await fetch(`/hierarchy/${currentDatabase}/search`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: query, top_k: 10 })
            });
            
            if (!res.ok) {
                throw new Error(`HTTP ${res.status}`);
            }
            
            const data = await res.json();
            displayCatalogSearchResults(data.categories);
            
        } catch (e) {
            console.error('❌ Ошибка поиска категорий:', e);
            catalogSearchResults.innerHTML = `
                <div class="catalog-search-empty">
                    <i class="fas fa-exclamation-triangle" style="color: var(--danger);"></i>
                    <div>Ошибка поиска</div>
                </div>
            `;
        } finally {
            catalogSearchResults.classList.remove('loading');
        }
    }

    /**
     * Отображение результатов поиска по каталогу.
     * @param {Array} categories - Массив найденных категорий
     */
    function displayCatalogSearchResults(categories) {
        if (!catalogSearchResults) return;
        
        if (!categories || categories.length === 0) {
            catalogSearchResults.innerHTML = `
                <div class="catalog-search-empty">
                    <i class="fas fa-folder-open" style="opacity: 0.5;"></i>
                    <div>Категории не найдены</div>
                </div>
            `;
            return;
        }
        
        // Подсказка о множественном выборе
        let html = `
            <div class="catalog-search-hint">
                <i class="fas fa-keyboard"></i> Ctrl+клик для добавления в фильтр
            </div>
        `;
        
        categories.forEach(cat => {
            const scoreText = cat.rerank_score 
                ? `${(cat.rerank_score * 100).toFixed(0)}%`
                : `${cat.hits} совп.`;
            
            // Проверяем, выбрана ли уже эта категория
            const isSelected = selectedPaths.some(p => p.path === cat.path);
            const selectedClass = isSelected ? ' selected' : '';
            
            // Название папки - последний сегмент пути
            const folderName = cat.name || cat.path.split(' → ').pop();
            
            // Полный путь иерархии от корня до текущей папки
            // Всегда показываем cat.path - это и есть полный путь через " → "
            const fullHierarchyPath = cat.path;
            
            html += `
                <div class="catalog-search-result${selectedClass}" 
                     data-path="${escapeHtml(cat.path)}" 
                     data-level="${cat.level}">
                    <div class="catalog-search-result-name">
                        ${isSelected ? '<i class="fas fa-check-circle" style="color: var(--success); margin-right: 5px;"></i>' : ''}
                        <i class="fas fa-folder" style="color: #f59e0b; margin-right: 5px;"></i>
                        ${escapeHtml(folderName)}
                        <span class="catalog-search-result-score">${scoreText}</span>
                    </div>
                    <div class="catalog-search-result-path">${escapeHtml(fullHierarchyPath)}</div>
                </div>
            `;
        });
        
        catalogSearchResults.innerHTML = html;
        
        // Добавляем обработчики кликов по результатам
        catalogSearchResults.querySelectorAll('.catalog-search-result').forEach(result => {
            result.addEventListener('click', async (event) => {
                const path = result.dataset.path;
                const level = parseInt(result.dataset.level);
                
                // Выбираем категорию (передаём event для проверки Ctrl)
                // ВАЖНО: await нужен так как функция async!
                await selectCategoryFromSearch(path, level, event);
                
                // При Ctrl+клике НЕ скрываем результаты (чтобы можно было выбрать ещё)
                if (event.ctrlKey || event.metaKey) {
                    // Обновляем визуальное состояние ПОСЛЕ изменения selectedPaths
                    const isNowSelected = selectedPaths.some(p => p.path === path);
                    result.classList.toggle('selected', isNowSelected);
                    
                    // Обновляем иконку выбора
                    const nameEl = result.querySelector('.catalog-search-result-name');
                    const checkIcon = nameEl.querySelector('.fa-check-circle');
                    
                    if (isNowSelected && !checkIcon) {
                        // Добавляем галочку при выборе
                        nameEl.insertAdjacentHTML('afterbegin', 
                            '<i class="fas fa-check-circle" style="color: var(--success); margin-right: 5px;"></i>'
                        );
                    } else if (!isNowSelected && checkIcon) {
                        // Убираем галочку при снятии выбора
                        checkIcon.remove();
                    }
                } else {
                    // Обычный клик - скрываем результаты и очищаем поиск
                    hideCatalogSearchResults();
                    catalogSearchInput.value = '';
                    if (catalogSearchClear) {
                        catalogSearchClear.classList.add('hidden');
                    }
                }
            });
        });
    }

    /**
     * Скрытие результатов поиска по каталогу.
     */
    function hideCatalogSearchResults() {
        if (catalogSearchResults) {
            catalogSearchResults.classList.add('hidden');
        }
    }

    /**
     * Раскрытие пути в дереве (с ленивой загрузкой).
     * Последовательно раскрывает все РОДИТЕЛЬСКИЕ категории вдоль пути и загружает их детей.
     * Оптимизировано для быстрого перехода без лишних задержек.
     * @param {string} targetPath - Путь к категории (например, "Арматура → Краны → Шаровые")
     */
    async function expandPathInTree(targetPath) {
        const separator = ' → ';
        const parts = targetPath.split(separator);
        
        console.log(`🔓 Раскрытие пути: "${targetPath}"`);
        
        // Проходим по РОДИТЕЛЬСКИМ уровням пути
        let currentPath = '';
        for (let i = 0; i < parts.length - 1; i++) {
            currentPath += (i > 0 ? separator : '') + parts[i];
            
            // Находим узел
            // Используем Array.from для поиска, так как querySelector с CSS.escape может не сработать на сложных путях
            const node = Array.from(document.querySelectorAll('.tree-node')).find(n => n.dataset.path === currentPath);
            
            if (node) {
                const children = node.querySelector(':scope > .tree-children');
                const expandIcon = node.querySelector(':scope > .tree-node-header .tree-node-expand');
                
                // Если детей нужно загрузить
                if (children && !loadedPaths.has(currentPath)) {
                    console.log(`      ⬇️ Загрузка детей для "${currentPath}"`);
                    await loadChildren(currentPath, children);
                }
                
                // Раскрываем
                if (children && children.classList.contains('collapsed')) {
                    children.classList.remove('collapsed');
                    children.classList.add('expanded');
                    if (expandIcon) expandIcon.classList.add('expanded');
                }
            } else {
                console.warn(`   ⚠️ Узел "${currentPath}" не найден, прерывание цепочки`);
                return;
            }
        }
    }

    /**
     * Выбор категории из результатов поиска.
     * Раскрывает дерево до нужной категории и выделяет её.
     * 
     * Логика:
     * - Обычный клик: только переходит к категории в дереве для просмотра (НЕ меняет фильтр!)
     * - Ctrl+клик: добавляет/убирает категорию из фильтра
     * 
     * @param {string} path - Полный путь категории
     * @param {number} level - Уровень категории
     * @param {MouseEvent} event - Событие клика (для проверки Ctrl)
     */
    async function selectCategoryFromSearch(path, level, event) {
        // 1. Раскрываем путь (быстро, без искусственных задержек)
        await expandPathInTree(path);
        
        // 2. Находим целевой узел (он должен быть уже в DOM)
        const targetHeader = Array.from(document.querySelectorAll('.tree-node-header')).find(h => h.dataset.path === path);
        
        // Проверяем Ctrl+клик для добавления в фильтр
        const isCtrlClick = event && (event.ctrlKey || event.metaKey);
        
        if (isCtrlClick) {
            if (targetHeader) {
                toggleMultiSelect(path, level, targetHeader);
            } else {
                // Если узел не найден (что странно), работаем с данными
                const exists = selectedPaths.some(p => p.path === path);
                if (!exists) {
                    selectedPaths.push({ path, level });
                } else {
                    const index = selectedPaths.findIndex(p => p.path === path);
                    if (index > -1) selectedPaths.splice(index, 1);
                }
                updateMultiSelectUI();
            }
        } else {
            console.log(`📍 Переход к категории: "${path}"`);
        }
        
        // 3. Скроллим и подсвечиваем
        if (targetHeader) {
            // Подсвечиваем СРАЗУ (до окончания smooth scroll), чтобы пользователь
            // увидел, что scroll идёт в нужное место. Анимация 4.5s покрывает
            // время scroll + даёт ~3s на рассмотрение. При scrollend анимация
            // остаётся ещё ~1s — этого достаточно, чтобы глаз зафиксировал узел.
            targetHeader.classList.add('highlight-pulse');
            targetHeader.scrollIntoView({ behavior: 'smooth', block: 'center' });

            const cleanup = () => {
                targetHeader.classList.remove('highlight-pulse');
                clearTimeout(timer);
                window.removeEventListener('scrollend', cleanup);
            };
            const timer = setTimeout(cleanup, 5000);
            // Если браузер поддерживает scrollend — убрать подсветку как только
            // скролл реально закончился, и продлить ещё на 1.5s.
            if ('onscrollend' in window) {
                const onEnd = () => {
                    setTimeout(cleanup, 1500);
                    window.removeEventListener('scrollend', onEnd);
                };
                setTimeout(() => window.addEventListener('scrollend', onEnd, { once: true }), 50);
            }
        } else {
            console.warn(`⚠️ Целевой узел "${path}" не найден в DOM после раскрытия`);
        }
    }

    /**
     * Навигация в каталог по пути категорий из результатов поиска.
     * Вызывается при клике на путь категорий в таблице результатов.
     * 
     * Логика:
     * 1. Раскрыть sidebar каталога (если свёрнут)
     * 2. Раскрыть путь в дереве категорий
     * 3. Подсветить целевую категорию
     * 
     * @param {string} categoryPath - Путь категорий (например, "Арматура → Краны → Шаровые")
     */
    async function navigateToCategoryInCatalog(categoryPath) {
        if (!categoryPath) {
            console.warn('⚠️ Путь категории не указан');
            return;
        }
        
        console.log(`🔍 Навигация в каталог: "${categoryPath}"`);
        
        // 1. Раскрыть sidebar если свёрнут
        if (sidebarCollapsed) {
            toggleSidebar();
            // Небольшая задержка для анимации раскрытия
            await new Promise(resolve => setTimeout(resolve, 300));
        }
        
        // 2. Раскрываем путь в дереве категорий
        await expandPathInTree(categoryPath);
        
        // 3. Находим целевую категорию и подсвечиваем
        // Ищем заголовок с точным совпадением пути
        const targetHeader = Array.from(document.querySelectorAll('.tree-node-header'))
            .find(h => h.dataset.path === categoryPath);
        
        if (targetHeader) {
            // Подсветка до scroll (4.5s CSS + 5s JS timeout) — пользователь
            // успевает увидеть куда идёт scroll, даже если дерево длинное.
            targetHeader.classList.add('highlight-pulse');
            targetHeader.scrollIntoView({ behavior: 'smooth', block: 'center' });

            const cleanup = () => {
                targetHeader.classList.remove('highlight-pulse');
                clearTimeout(timer);
                window.removeEventListener('scrollend', cleanup);
            };
            const timer = setTimeout(cleanup, 5000);
            if ('onscrollend' in window) {
                const onEnd = () => {
                    setTimeout(cleanup, 1500);
                    window.removeEventListener('scrollend', onEnd);
                };
                setTimeout(() => window.addEventListener('scrollend', onEnd, { once: true }), 50);
            }

            console.log(`✅ Перешли к категории: "${categoryPath}"`);
        } else {
            // Категория не найдена - возможно путь неполный или данные ещё не загружены
            console.warn(`⚠️ Категория "${categoryPath}" не найдена в дереве`);
            
            // Попробуем найти родительскую категорию
            const parts = categoryPath.split(' → ');
            if (parts.length > 1) {
                const parentPath = parts.slice(0, -1).join(' → ');
                const parentHeader = Array.from(document.querySelectorAll('.tree-node-header'))
                    .find(h => h.dataset.path === parentPath);
                
                if (parentHeader) {
                    parentHeader.classList.add('highlight-pulse');
                    parentHeader.scrollIntoView({ behavior: 'smooth', block: 'center' });

                    const cleanupP = () => {
                        parentHeader.classList.remove('highlight-pulse');
                        clearTimeout(timerP);
                        window.removeEventListener('scrollend', cleanupP);
                    };
                    const timerP = setTimeout(cleanupP, 5000);
                    if ('onscrollend' in window) {
                        const onEndP = () => {
                            setTimeout(cleanupP, 1500);
                            window.removeEventListener('scrollend', onEndP);
                        };
                        setTimeout(() => window.addEventListener('scrollend', onEndP, { once: true }), 50);
                    }

                    console.log(`📁 Показана родительская категория: "${parentPath}"`);
                }
            }
        }
    }

    // Инициализируем поиск по каталогу
    initCatalogSearch();
});
