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
        headers: []
    },
    /** @type {Array} Загруженные строки данных для таблицы */
    dataRows: [],
    /** @type {string|null} Колонка сортировки */
    sortColumn: null,
    /** @type {string} Направление сортировки: 'asc' | 'desc' */
    sortDirection: 'asc'
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
        data: document.getElementById('viewData')
    },
    
    // Collections
    collectionsGrid: document.getElementById('collectionsGrid'),
    
    // Data Table
    dataTable: document.getElementById('dataTable'),
    dataTableBody: document.getElementById('dataTableBody'),
    loadMoreBtn: document.getElementById('loadMoreBtn'),
    
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
    mapCodeCol: document.getElementById('mapCodeCol'),
    mapDescCols: document.getElementById('mapDescCols'),
    descMultiSelect: document.getElementById('descMultiSelect'),
    descSelectedCount: document.getElementById('descSelectedCount'),
    
    importProgress: document.getElementById('importProgress'),
    importStatusText: document.getElementById('importStatusText'),
    
    importSteps: [
        document.getElementById('importStep1'),
        document.getElementById('importStep2'),
        document.getElementById('importStep3')
    ],
    importBtns: {
        back: document.getElementById('importBackBtn'),
        next: document.getElementById('importNextBtn'),
        upload: document.getElementById('importUploadBtn')
    },
    
    // Preview elements
    previewTable: document.getElementById('previewTable'),
    previewHead: document.getElementById('previewHead'),
    previewBody: document.getElementById('previewBody'),
    previewCount: document.getElementById('previewCount')
};

// === INITIALIZATION ===
document.addEventListener('DOMContentLoaded', () => {
    initAuth();
    initNavigation();
    initModals();
    initImportWizard();
    initCreateCollection();
    initAddRecord();
    initMultiSelect();
    initSorting();
});

// === AUTHENTICATION ===

/**
 * Инициализация аутентификации.
 * Проверяет сохранённый токен и настраивает обработчики.
 */
function initAuth() {
    // Проверяем есть ли сохранённый токен
    if (state.token) {
        // Валидируем токен через тестовый запрос
        validateToken().then(valid => {
            if (valid) {
                showApp();
            } else {
                // Токен невалиден - очищаем и показываем форму входа
                logout();
            }
        });
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
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({password: pwd})
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
    Object.values(els.views).forEach(v => v.classList.add('hidden'));
    
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
            const res1 = await fetch('/create_collection', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    collection_name: id,
                    description: name,
                    dimension: 1024,
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
                    thresholds: { cosine, rerank }
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
    els.dataTableBody.innerHTML = '';
    updateSortIcons();
    loadData();
};

async function loadData() {
    if (!state.activeCollection) return;
    
    try {
        const offsetQuery = state.dataOffset ? `&offset=${state.dataOffset}` : '';
        const res = await authFetch(`/admin/collections/${state.activeCollection}/data?limit=50${offsetQuery}`);
        const result = await res.json();
        
        state.dataOffset = result.next_offset;
        
        // Toggle Load More button
        if (!state.dataOffset) els.loadMoreBtn.classList.add('hidden');
        else els.loadMoreBtn.classList.remove('hidden');
        
        if (result.data.length === 0 && state.dataRows.length === 0) {
            els.dataTableBody.innerHTML = '<tr><td colspan="3" style="text-align:center; padding:30px; color:var(--adm-text-sec)">Записей не найдено. Добавьте новые!</td></tr>';
        } else {
            // Добавляем к существующим данным
            state.dataRows = state.dataRows.concat(result.data);
            renderDataTable();
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') {
            console.error('Failed to load data:', e);
        }
    }
}

function renderDataTable() {
    els.dataTableBody.innerHTML = '';
    
    // Применяем сортировку если задана
    let sortedRows = [...state.dataRows];
    if (state.sortColumn) {
        sortedRows.sort((a, b) => {
            const valA = (a[state.sortColumn] || '').toString().toLowerCase();
            const valB = (b[state.sortColumn] || '').toString().toLowerCase();
            
            if (valA < valB) return state.sortDirection === 'asc' ? -1 : 1;
            if (valA > valB) return state.sortDirection === 'asc' ? 1 : -1;
            return 0;
        });
    }
    
    sortedRows.forEach(row => {
        renderRow(row);
    });
    
    initInlineEdit();
}

function renderRow(row) {
    const tr = document.createElement('tr');
    tr.dataset.rowId = row.id;
    tr.innerHTML = `
        <td class="editable" data-id="${row.id}" data-field="code">${row.code}</td>
        <td class="editable" data-id="${row.id}" data-field="description">${row.description}</td>
        <td>
            <button class="btn btn-danger" style="padding: 6px;" onclick="deleteRecord('${row.id}')">
                <i class="fas fa-trash"></i>
            </button>
        </td>
    `;
    els.dataTableBody.appendChild(tr);
}

// === SORTING ===
function initSorting() {
    document.querySelectorAll('th.sortable').forEach(th => {
        th.style.cursor = 'pointer';
        th.addEventListener('click', () => {
            const column = th.dataset.sort;
            
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

function updateSortIcons() {
    document.querySelectorAll('th.sortable').forEach(th => {
        const icon = th.querySelector('.sort-icon');
        const column = th.dataset.sort;
        
        if (state.sortColumn === column) {
            icon.className = `fas fa-sort-${state.sortDirection === 'asc' ? 'up' : 'down'} sort-icon active`;
        } else {
            icon.className = 'fas fa-sort sort-icon';
        }
    });
}

els.loadMoreBtn.addEventListener('click', loadData);

// === ADD RECORD ===
function initAddRecord() {
    els.saveRecBtn.addEventListener('click', async () => {
        const code = els.newRecCode.value.trim();
        const desc = els.newRecDesc.value.trim();
        
        if (!code || !desc) return alert('Оба поля обязательны');
        
        try {
            const res = await fetch('/update_record', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    code: code,
                    description: desc,
                    database: state.activeCollection
                })
            });
            
            if (res.ok) {
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
function initInlineEdit() {
    document.querySelectorAll('.editable').forEach(td => {
        if (td.dataset.bound) return;
        td.dataset.bound = true;
        
        td.addEventListener('dblclick', function() {
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
            
            const save = async () => {
                const newVal = input.value;
                if (newVal === originalVal) {
                    this.innerHTML = originalVal;
                    this.classList.remove('editing');
                    return;
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
                        this.innerHTML = newVal;
                        // Обновляем в state
                        const row = state.dataRows.find(r => r.id === id);
                        if (row) row[field] = newVal;
                    } else {
                        alert('Ошибка обновления');
                        this.innerHTML = originalVal;
                    }
                } catch (e) {
                    if (e.message !== 'Unauthorized') {
                        alert('Ошибка обновления');
                        this.innerHTML = originalVal;
                    }
                } finally {
                    this.classList.remove('editing');
                }
            };
            
            input.addEventListener('blur', save);
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') input.blur();
            });
        });
    });
}

window.deleteRecord = async (id) => {
    if (!confirm('Вы уверены, что хотите удалить эту запись?')) return;
    try {
        await authFetch(`/admin/collections/${state.activeCollection}/data/${id}`, {
            method: 'DELETE'
        });
        // Удаляем из state
        state.dataRows = state.dataRows.filter(r => r.id !== id);
        // Удаляем из DOM
        const tr = document.querySelector(`tr[data-row-id="${id}"]`);
        if (tr) tr.remove();
    } catch (e) {
        if (e.message !== 'Unauthorized') {
            alert('Ошибка удаления');
        }
    }
};

// === IMPORT WIZARD ===
window.openImport = (name) => {
    state.activeCollection = name;
    els.importTarget.value = name;
    
    els.pasteArea.value = '';
    state.importData = { raw: [], headers: [] };
    showImportStep(0);
    
    openModal('import');
};

function initImportWizard() {
    els.pasteArea.addEventListener('paste', (e) => {
        setTimeout(() => {
            const text = els.pasteArea.value.trim();
            if (text) processPastedData(text);
        }, 100);
    });

    els.importBtns.next.addEventListener('click', () => {
        const text = els.pasteArea.value.trim();
        if (!text) return alert('Сначала вставьте данные.');
        processPastedData(text);
    });
    
    els.importBtns.back.addEventListener('click', () => {
        showImportStep(0);
    });
    
    els.importBtns.upload.addEventListener('click', async () => {
        const codeCol = els.mapCodeCol.value;
        const descCols = Array.from(els.mapDescCols.querySelectorAll('input:checked')).map(cb => cb.value);
        
        if (descCols.length === 0) return alert('Выберите хотя бы одну колонку описания.');
        
        const records = state.importData.raw.map(r => {
            return {
                code: r[codeCol],
                description: descCols.map(c => r[c]).filter(Boolean).join(' → '),
                meta: r
            };
        });
        
        const payload = {
            collection_name: state.activeCollection,
            records: records,
            recreate: false
        };
        
        showImportStep(2);
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
    });
}

function getSelectedDelimiter() {
    const selected = document.querySelector('input[name="delimiter"]:checked');
    return selected ? selected.value : 'tab';
}

function detectDelimiter(text) {
    // Берём первую строку для анализа
    const firstLine = text.split('\n')[0] || '';
    
    // Считаем количество каждого разделителя
    const tabCount = (firstLine.match(/\t/g) || []).length;
    const semicolonCount = (firstLine.match(/;/g) || []).length;
    const commaCount = (firstLine.match(/,/g) || []).length;
    
    // Выбираем разделитель с максимальным количеством
    if (tabCount >= semicolonCount && tabCount >= commaCount && tabCount > 0) {
        return '\t';
    } else if (semicolonCount >= commaCount && semicolonCount > 0) {
        return ';';
    } else if (commaCount > 0) {
        return ',';
    }
    
    // По умолчанию tab
    return '\t';
}

function processPastedData(text) {
    // Определяем разделитель
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
    
    // Разбиваем на строки и ячейки
    const rows = text.split('\n').map(r => r.split(delimiter)).filter(r => r.some(cell => cell.trim()));
    
    if (rows.length < 2) {
        alert('Недостаточно данных. Нужна минимум 1 строка заголовков и 1 строка данных.\n\nПроверьте выбранный разделитель!');
        return;
    }
    
    // Проверяем что получилось больше 1 колонки
    if (rows[0].length === 1) {
        alert('Обнаружена только 1 колонка. Возможно, выбран неверный разделитель.\n\nПопробуйте другой разделитель или "Авто".');
        return;
    }
    
    state.importData.headers = rows[0].map(h => h.trim()).filter(h => h);
    state.importData.raw = rows.slice(1).map(row => {
        const obj = {};
        state.importData.headers.forEach((h, i) => obj[h] = (row[i] || '').trim());
        return obj;
    }).filter(obj => Object.values(obj).some(v => v));
    
    els.mapCodeCol.innerHTML = state.importData.headers.map(h => 
        `<option value="${h}">${h}</option>`
    ).join('');
    
    els.mapDescCols.innerHTML = state.importData.headers.map((h, idx) => `
        <div class="option-item">
            <input type="checkbox" value="${h}" id="chk_${h.replace(/\s/g, '_')}" ${idx > 0 ? 'checked' : ''}>
            <label for="chk_${h.replace(/\s/g, '_')}" class="option-text">${h}</label>
        </div>
    `).join('');
    
    updateSelectedCount();
    renderPreviewTable();
    
    showImportStep(1);
}

function renderPreviewTable() {
    els.previewHead.innerHTML = `<tr>${state.importData.headers.map(h => `<th>${h}</th>`).join('')}</tr>`;
    
    const previewRows = state.importData.raw.slice(0, 5);
    els.previewBody.innerHTML = previewRows.map(row => 
        `<tr>${state.importData.headers.map(h => `<td title="${row[h] || ''}">${row[h] || '-'}</td>`).join('')}</tr>`
    ).join('');
    
    els.previewCount.innerText = `${state.importData.raw.length} строк`;
}

function updateSelectedCount() {
    const count = els.mapDescCols.querySelectorAll('input:checked').length;
    els.descSelectedCount.innerText = `Выбрано: ${count}`;
}

// === CUSTOM MULTI-SELECT ===
function initMultiSelect() {
    const trigger = els.descMultiSelect.querySelector('.select-trigger');
    const options = els.descMultiSelect.querySelector('.select-options');
    
    trigger.addEventListener('click', () => {
        trigger.classList.toggle('active');
        options.classList.toggle('open');
    });
    
    document.addEventListener('click', (e) => {
        if (!els.descMultiSelect.contains(e.target)) {
            trigger.classList.remove('active');
            options.classList.remove('open');
        }
    });
    
    options.addEventListener('change', updateSelectedCount);
}

function showImportStep(idx) {
    els.importSteps.forEach((s, i) => {
        if (i === idx) s.classList.add('active');
        else s.classList.remove('active');
    });
    
    if (idx === 0) {
        els.importBtns.back.classList.add('hidden');
        els.importBtns.next.classList.remove('hidden');
        els.importBtns.upload.classList.add('hidden');
    } else if (idx === 1) {
        els.importBtns.back.classList.remove('hidden');
        els.importBtns.next.classList.add('hidden');
        els.importBtns.upload.classList.remove('hidden');
    } else {
        els.importBtns.back.classList.add('hidden');
        els.importBtns.next.classList.add('hidden');
        els.importBtns.upload.classList.add('hidden');
    }
}

async function pollJob(jobId) {
    els.importStatusText.innerText = 'В очереди...';
    els.importProgress.style.width = '0%';
    
    const interval = setInterval(async () => {
        try {
            const res = await authFetch('/admin/jobs');
            const jobs = await res.json();
            const job = jobs.find(j => j.id === jobId);
        
        if (job) {
            els.importProgress.style.width = `${job.progress}%`;
            
            const statusText = {
                'pending': 'Ожидание',
                'processing': 'Обработка',
                'completed': 'Завершено',
                'error': 'Ошибка'
            };
            
            els.importStatusText.innerText = `${statusText[job.status] || job.status} (${job.progress}%)`;
            
                if (job.status === 'completed') {
                clearInterval(interval);
                
                // Инвалидируем кэш иерархии для обновлённой коллекции
                fetch(`/hierarchy/${state.activeCollection}/invalidate`, { method: 'POST' })
                    .then(() => console.log('✅ Кэш иерархии очищен'))
                    .catch(e => console.warn('⚠️ Не удалось очистить кэш иерархии:', e));
                
                setTimeout(() => {
                    alert('Импорт завершён!\n\nПоля path_level_N автоматически сгенерированы для иерархического каталога.');
                    closeModal('import');
                    loadCollections();
                }, 500);
            } else if (job.status === 'error') {
                clearInterval(interval);
                alert(`Ошибка: ${job.error}`);
                closeModal('import');
            }
        }
        } catch (e) {
            if (e.message === 'Unauthorized') {
                clearInterval(interval);
            }
        }
    }, 1500);
}

// === JOBS VIEW ===
async function loadJobs() {
    try {
        const res = await authFetch('/admin/jobs');
        const jobs = await res.json();
    
    const statusText = {
        'pending': 'Ожидание',
        'processing': 'Обработка',
        'completed': 'Завершено',
        'error': 'Ошибка'
    };
    
        els.jobsTableBody.innerHTML = jobs.map(j => `
            <tr>
                <td style="font-family:monospace; font-size:0.8rem">${j.id.slice(0, 8)}...</td>
                <td>${j.type === 'import_batch' ? 'Импорт' : j.type}</td>
                <td><span class="status-badge ${j.status === 'completed' ? 'status-visible' : 'status-hidden'}">${statusText[j.status] || j.status}</span></td>
                <td>
                    <div class="progress-bar-container" style="width: 100px; height: 6px;">
                        <div class="progress-bar-fill" style="width: ${j.progress}%"></div>
                    </div>
                </td>
                <td>${new Date(j.created_at * 1000).toLocaleString('ru-RU')}</td>
            </tr>
        `).join('');
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

// === MODAL UTILS ===
function initModals() {
    document.querySelectorAll('.modal-close, .modal-close-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const modal = this.closest('.modal-overlay');
            modal.classList.remove('active');
        });
    });
}

function openModal(name) {
    if (els.modals[name]) els.modals[name].classList.add('active');
}

function closeModal(name) {
    if (els.modals[name]) els.modals[name].classList.remove('active');
}
