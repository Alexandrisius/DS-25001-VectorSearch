
document.addEventListener('DOMContentLoaded', function () {
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

    const customSelectWrapper = document.getElementById('customSelect');
    const customSelectTrigger = customSelectWrapper.querySelector('.custom-select-trigger');
    const customOptionsContainer = document.getElementById('customOptions');
    const customSelectValue = document.getElementById('customSelectValue');

    const themeToggle = document.getElementById('themeToggle');
    const themeIcon = themeToggle.querySelector('i');
    const themeText = themeToggle.querySelector('span');

    let currentDatabase = 'ksr_main';
    let databases = [];
    let currentQuery = '';
    let currentResults = [];

    queryInput.focus();
    loadAvailableDatabases();
    initTheme();

    // --- THEME TOGGLE LOGIC (ТЁМНАЯ ПО УМОЛЧАНИЮ) ---

    function initTheme() {
        const savedTheme = localStorage.getItem('theme') || 'dark'; // ИЗМЕНЕНО: по умолчанию dark
        setTheme(savedTheme);
    }

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
    });

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

    function clearResults() {
        resultsBody.innerHTML = `
                    <tr><td colspan="6" style="text-align: center; padding: 60px 20px; color: var(--text-secondary);">
                    Результаты очищены</td></tr>`;
        errorContainer.classList.add('hidden');
        statusInfo.textContent = 'Готов к работе';
        statusInfo.style.color = 'var(--success)';
    }

    function createScoreBar(val) {
        const pct = Math.min(100, val * 100);
        return `<div class="progress-bg"><div class="progress-fill" style="width:${pct}%"></div></div>`;
    }

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

    function renderDbCards() {
        let html = '';
        databases.forEach(db => {
            const active = db.name === currentDatabase ? 'active' : '';
            html += `
                        <div class="db-card ${active}" data-name="${db.name}">
                            <div class="db-card-name">${db.description.split('(')[0]}</div>
                            <div class="db-card-desc">${db.record_count.toLocaleString()} записей</div>
                        </div>`;
        });
        databaseOptions.innerHTML = html;
    }

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
            document.getElementById('rerankThreshold').textContent = (db.thresholds?.rerank || 0.6).toFixed(2);
            document.getElementById('cosineThreshold').textContent = (db.thresholds?.cosine || 0.45).toFixed(2);
            processingInfo.textContent = `Выбрана база: ${db.description.split('(')[0]}`;
        }
    }

    async function performSearch() {
        const q = queryInput.value.trim();
        if (!q) return;

        setLoading(true);
        errorContainer.classList.add('hidden');

        try {
            const res = await fetch('/match', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: q, database: currentDatabase })
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

    function displayResults(data) {
        currentQuery = data.query;
        currentResults = data.candidates;
        processingTimeElement.textContent = data.processing_time.toFixed(2) + 's';
        statusInfo.textContent = `Найдено: ${data.candidates.length}`;
        statusInfo.style.color = 'var(--success)';

        const dbName = databases.find(d => d.name === currentDatabase)?.description.split('(')[0] || currentDatabase;
        processingInfo.textContent = `Поиск завершен по базе "${dbName}"`;

        let html = '';
        data.candidates.forEach(c => {
            const isTop = c.rank === 1;
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
                            <td>${c.description}</td>
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
});
