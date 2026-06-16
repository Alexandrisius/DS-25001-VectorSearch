/**
 * Аналитика поиска — дашборд для админа.
 *
 * Загружает 4 endpoint'а при открытии вкладки и при нажатии "Обновить":
 *   /admin/analytics/kpi
 *   /admin/analytics/recent
 *   /admin/analytics/zero-results
 *   /admin/analytics/slow
 *
 * Период (1ч / 24ч / неделя / месяц) управляет всеми запросами.
 */

const ANALYTICS_TOKEN_KEY = 'adminToken';
let _refreshTimer = null;

function authHeader() {
    const t = localStorage.getItem(ANALYTICS_TOKEN_KEY);
    return t ? { Authorization: `Bearer ${t}` } : {};
}

async function fetchJson(url) {
    const res = await fetch(url, { headers: authHeader() });
    if (!res.ok) {
        if (res.status === 401) {
            // Токен протух — перезагрузка, auth.js сам покажет логин
            location.reload();
            return null;
        }
        throw new Error(`${res.status} ${res.statusText}`);
    }
    return res.json();
}

function fmtTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function fmtDelta(curr, prev) {
    if (prev == null || curr == null) return '—';
    if (prev === 0) {
        if (curr === 0) return 'без изменений';
        return `+${curr}`;
    }
    const diff = curr - prev;
    const pct = ((diff / prev) * 100).toFixed(0);
    if (diff === 0) return 'без изменений';
    const sign = diff > 0 ? '+' : '';
    const cls = diff > 0 ? 'kpi-card__delta--up' : 'kpi-card__delta--down';
    return `<span class="${cls}">${sign}${diff} (${sign}${pct}%)</span> vs пред. период`;
}

function fmtMs(v) {
    if (v == null) return '—';
    if (v >= 1000) return `${(v / 1000).toFixed(2)}s`;
    return `${v}ms`;
}

function branchTag(branch) {
    // Уверенность top-1 результата (адаптивный порог реранкера)
    const meta = {
        confident: {
            label: 'Уверенно',
            tip: 'Top-1 результат реранкера выше порога — модель уверена в выдаче',
        },
        uncertain: {
            label: 'Сомнительно',
            tip: 'Top-1 ниже высокого порога — возможно стоит уточнить запрос',
        },
        low_confidence: {
            label: 'Низкая',
            tip: 'Все результаты низкого качества — пользователь не нашёл подходящего',
        },
    };
    if (!branch || !meta[branch]) {
        return '<span class="branch-tag branch-tag--empty">—</span>';
    }
    const m = meta[branch];
    return `<span class="branch-tag branch-tag--${branch}" title="${m.tip}">${m.label}</span>`;
}

function renderTimings(t) {
    if (!t) return '<span class="t-ok">—</span>';
    const total = t.total_ms || 0;
    const rerank = t.rerank_ms || 0;
    const embed = t.embed_ms || 0;
    const qdrant = t.qdrant_ms || 0;
    const bm25 = t.bm25_ms || 0;
    const rerankCls = rerank > 1500 ? 't-slow' : rerank < 500 ? 't-fast' : 't-ok';
    const embedCls = embed > 500 ? 't-slow' : 't-fast';
    return `
        <div class="timing-cell">
            <div><strong>total</strong>: ${total}</div>
            <div>rerank: <span class="${rerankCls}">${rerank}</span></div>
            <div>embed: <span class="${embedCls}">${embed}</span> · qdrant: ${qdrant} · bm25: ${bm25}</div>
        </div>
    `;
}

/**
 * Колонка "Что сделал" — что ИМЕННО сотрудник сделал после поиска:
 *  - скопировал (какой код утащил в буфер)
 *  - дизлайкнул (какие коды отверг)
 *
 * Если ничего — показываем "—" с пояснением.
 */
function renderActions(copiedCodes, dislikedCodes) {
    const copied = (copiedCodes || []).filter(Boolean);
    const disliked = (dislikedCodes || []).filter(Boolean);
    const parts = [];

    if (copied.length > 0) {
        const chips = copied.slice(0, 3)
            .map((c) => `<span class="action-chip action-chip--copy" title="Скопировал в буфер">${escapeHtml(c)}</span>`)
            .join(' ');
        const more = copied.length > 3 ? ` <small class="action-more">+${copied.length - 3}</small>` : '';
        parts.push(`
            <div class="action-row action-row--copy">
                <i class="fas fa-copy" aria-hidden="true"></i>
                <span class="action-label">Скопировал${copied.length > 1 ? ` (${copied.length})` : ''}:</span>
                ${chips}${more}
            </div>
        `);
    }

    if (disliked.length > 0) {
        const chips = disliked.slice(0, 3)
            .map((c) => `<span class="action-chip action-chip--dislike" title="Дизлайкнул">${escapeHtml(c)}</span>`)
            .join(' ');
        const more = disliked.length > 3 ? ` <small class="action-more">+${disliked.length - 3}</small>` : '';
        parts.push(`
            <div class="action-row action-row--dislike">
                <i class="fas fa-thumbs-down" aria-hidden="true"></i>
                <span class="action-label">Дизлайк${disliked.length > 1 ? ` (${disliked.length})` : ''}:</span>
                ${chips}${more}
            </div>
        `);
    }

    if (parts.length === 0) {
        return `<div class="action-empty" title="Сотрудник не отреагировал на выдачу">
            <i class="fas fa-circle" aria-hidden="true"></i> <span>—</span>
        </div>`;
    }

    return `<div class="actions">${parts.join('')}</div>`;
}

async function loadKpi(hours) {
    const data = await fetchJson(`/admin/analytics/kpi?hours=${hours}`);
    if (!data) return;
    document.getElementById('kpiSearches').textContent = data.searches.toLocaleString('ru-RU');
    document.getElementById('kpiSearchesDelta').innerHTML = fmtDelta(data.searches, data.prev.searches);
    document.getElementById('kpiZeroPct').textContent = `${data.zero_result_pct}%`;
    document.getElementById('kpiZeroDelta').innerHTML = fmtDelta(data.zero_result_pct, data.prev.zero_result_pct);
    document.getElementById('kpiLatency').textContent = `${data.p95_total_ms} / ${data.p50_total_ms}`;
    document.getElementById('kpiLatencyDelta').innerHTML = fmtDelta(data.avg_total_ms, data.prev.avg_total_ms);
    document.getElementById('kpiUsers').textContent = data.unique_users.toLocaleString('ru-RU');
    document.getElementById('kpiUsersDelta').textContent =
        `уникальных сессий: ${data.unique_sessions} · ошибок: ${data.errors}`;

    // Цвет карточки zero-result по порогам (Kendra/Meilisearch best practice)
    const card = document.getElementById('kpiZeroCard');
    card.classList.remove('kpi-card--ok', 'kpi-card--warn', 'kpi-card--bad');
    if (data.zero_result_pct < 3) card.classList.add('kpi-card--ok');
    else if (data.zero_result_pct < 10) card.classList.add('kpi-card--warn');
    else card.classList.add('kpi-card--bad');
}

async function loadRecent(hours) {
    const data = await fetchJson(`/admin/analytics/recent?hours=${hours}&limit=100`);
    const body = document.getElementById('analyticsRecentBody');
    if (!data || !data.items?.length) {
        body.innerHTML = `<tr><td colspan="8" class="analytics-empty">
            <i class="fas fa-inbox" aria-hidden="true"></i> Нет поисков за выбранный период
        </td></tr>`;
        return;
    }
    body.innerHTML = data.items
        .map((r) => {
            const ip = r.user_ip || '—';
            return `
            <tr>
                <td title="${r.ts || ''}">${fmtTime(r.ts)}</td>
                <td><span class="mono" title="session: ${r.session_id || ''}">${ip}</span></td>
                <td>${escapeHtml(r.query || '')}</td>
                <td>${escapeHtml(r.collection || '')}</td>
                <td>${r.candidates_count}</td>
                <td>${branchTag(r.branch)}</td>
                <td>${renderTimings(r)}</td>
                <td>${renderActions(r.copied_codes, r.disliked_codes)}</td>
            </tr>`;
        })
        .join('');
}

async function loadZero(daysBack) {
    const data = await fetchJson(`/admin/analytics/zero-results?days=${daysBack}&limit=50`);
    const body = document.getElementById('analyticsZeroBody');
    if (!data || !data.items?.length) {
        body.innerHTML = `<tr><td colspan="4" class="analytics-empty">
            <i class="fas fa-check-circle" aria-hidden="true"></i> Ни одного zero-result — отлично!
        </td></tr>`;
        return;
    }
    body.innerHTML = data.items
        .map((r) => `
        <tr>
            <td>${escapeHtml(r.query || '')}</td>
            <td>${r.cnt}</td>
            <td>${r.unique_users || 0}</td>
            <td>${fmtTime(r.last_seen)}</td>
        </tr>`)
        .join('');
}

async function loadSlow(hours) {
    const data = await fetchJson(`/admin/analytics/slow?hours=${hours}&limit=20&threshold_ms=2000`);
    const body = document.getElementById('analyticsSlowBody');
    if (!data || !data.items?.length) {
        body.innerHTML = `<tr><td colspan="5" class="analytics-empty">
            <i class="fas fa-bolt" aria-hidden="true"></i> Ни одного запроса > 2с
        </td></tr>`;
        return;
    }
    body.innerHTML = data.items
        .map((r) => `
        <tr>
            <td>${fmtTime(r.ts)}</td>
            <td>${escapeHtml(r.query || '')}</td>
            <td><strong>${r.total_ms}</strong> мс</td>
            <td>${r.rerank_ms || '—'} мс</td>
            <td><span class="mono">${r.user_ip || '—'}</span></td>
        </tr>`)
        .join('');
}

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

async function refreshAll() {
    const hours = parseInt(document.getElementById('analyticsHours').value, 10) || 24;
    const daysBack = hours <= 24 ? 7 : hours <= 168 ? 30 : 90;
    const updated = document.getElementById('analyticsUpdated');
    updated.textContent = 'Обновление…';

    try {
        await Promise.all([loadKpi(hours), loadRecent(hours), loadZero(daysBack), loadSlow(hours)]);
        updated.textContent = `Обновлено: ${new Date().toLocaleTimeString('ru-RU')}`;
    } catch (e) {
        updated.textContent = `Ошибка: ${e.message}`;
        console.error('analytics refresh failed:', e);
    }
}

/**
 * Инициализация модуля. Вызывается из main.js при загрузке админки.
 * При открытии вкладки Аналитика — refreshAll() + автообновление каждые 30с.
 */
export function initAnalytics() {
    const refreshBtn = document.getElementById('analyticsRefreshBtn');
    const hoursSelect = document.getElementById('analyticsHours');
    if (refreshBtn) refreshBtn.addEventListener('click', refreshAll);
    if (hoursSelect) hoursSelect.addEventListener('change', refreshAll);

    // Слушаем клик по вкладке навигации (вызывается из navigation.js)
    document.addEventListener('analytics:view-shown', () => {
        refreshAll();
        if (_refreshTimer) clearInterval(_refreshTimer);
        _refreshTimer = setInterval(refreshAll, 30000); // каждые 30 сек
    });
    document.addEventListener('analytics:view-hidden', () => {
        if (_refreshTimer) {
            clearInterval(_refreshTimer);
            _refreshTimer = null;
        }
    });
}
