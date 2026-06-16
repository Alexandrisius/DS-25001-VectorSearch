/**
 * Аналитика поиска — дашборд для админа.
 *
 * Загружает 4 endpoint'а при открытии вкладки и при нажатии "Обновить":
 *   /admin/analytics/kpi
 *   /admin/analytics/recent
 *   /admin/analytics/zero-results
 *   /admin/analytics/slow
 *
 * Период (1ч / 24ч / 7д / 30д) управляет всеми запросами.
 * Авто-обновление каждые 30с пока вкладка открыта.
 */

const ANALYTICS_TOKEN_KEY = 'adminToken';
let _refreshTimer = null;

const SLOW_THRESHOLD_MS = 2000;

function authHeader() {
    const t = localStorage.getItem(ANALYTICS_TOKEN_KEY);
    return t ? { Authorization: `Bearer ${t}` } : {};
}

async function fetchJson(url) {
    const res = await fetch(url, { headers: authHeader() });
    if (!res.ok) {
        if (res.status === 401) {
            location.reload();
            return null;
        }
        throw new Error(`${res.status} ${res.statusText}`);
    }
    return res.json();
}

/**
 * Форматирует ISO timestamp в "YYYY-MM-DD HH:MM:SS" (UTC).
 * Абсолютный формат — удобен для аудита и сортировки глазами.
 */
function fmtTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    const pad = (n) => String(n).padStart(2, '0');
    return (
        `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
        `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
    );
}

function fmtTimeShort(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function fmtDelta(curr, prev, unit = '') {
    if (prev == null || curr == null) return '—';
    if (prev === 0 && curr === 0) return '—';
    const diff = curr - prev;
    if (diff === 0) return '—';
    const sign = diff > 0 ? '+' : '';
    const cls = diff > 0 ? 'kpi-card__delta--up' : 'kpi-card__delta--down';
    const pct = prev !== 0 ? ` (${sign}${((diff / prev) * 100).toFixed(0)}%)` : '';
    return `<span class="${cls}">${sign}${diff}${unit}${pct}</span>`;
}

function branchTag(branch) {
    // Уверенность top-1 результата (адаптивный порог реранкера)
    const meta = {
        confident: {
            label: 'High',
            tip: 'rerank_score ≥ adaptive_confident_min — высокая уверенность в top-1',
        },
        uncertain: {
            label: 'Medium',
            tip: 'rerank_score в диапазоне [adaptive_uncertain_min, adaptive_confident_min)',
        },
        low_confidence: {
            label: 'Low',
            tip: 'rerank_score < adaptive_uncertain_min — fallback на cosine similarity',
        },
    };
    if (!branch || !meta[branch]) {
        return '<span class="branch-tag branch-tag--empty">N/A</span>';
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
            <div class="timing-row timing-row--primary">${total}<span class="timing-unit">ms</span></div>
            <div class="timing-row">rerank <span class="${rerankCls}">${rerank}</span></div>
            <div class="timing-row">embed <span class="${embedCls}">${embed}</span> · qdrant ${qdrant} · bm25 ${bm25}</div>
        </div>
    `;
}

/**
 * Колонка "Действия" — компактные chips с количеством.
 * Без текстовых префиксов "Скопировал:" / "Дизлайк:" — иконки и цвет достаточны.
 */
function renderActions(copiedCodes, dislikedCodes) {
    const copied = (copiedCodes || []).filter(Boolean);
    const disliked = (dislikedCodes || []).filter(Boolean);
    const parts = [];

    if (copied.length > 0) {
        const visible = copied.slice(0, 2);
        const more = copied.length > 2 ? `+${copied.length - 2}` : '';
        const chips = visible
            .map((c) => `<span class="action-chip action-chip--copy" title="Скопировано: ${escapeHtml(c)}">${escapeHtml(c)}</span>`)
            .join(' ');
        const moreEl = more ? `<span class="action-more">${more}</span>` : '';
        parts.push(`
            <div class="action-row action-row--copy" title="Скопировано ${copied.length} код(ов)">
                <span class="action-count">${copied.length}</span>
                <i class="fas fa-copy action-icon" aria-hidden="true"></i>
                ${chips}${moreEl}
            </div>
        `);
    }

    if (disliked.length > 0) {
        const visible = disliked.slice(0, 2);
        const more = disliked.length > 2 ? `+${disliked.length - 2}` : '';
        const chips = visible
            .map((c) => `<span class="action-chip action-chip--dislike" title="Отклонено: ${escapeHtml(c)}">${escapeHtml(c)}</span>`)
            .join(' ');
        const moreEl = more ? `<span class="action-more">${more}</span>` : '';
        parts.push(`
            <div class="action-row action-row--dislike" title="Отклонено ${disliked.length} код(ов)">
                <span class="action-count">${disliked.length}</span>
                <i class="fas fa-thumbs-down action-icon" aria-hidden="true"></i>
                ${chips}${moreEl}
            </div>
        `);
    }

    if (parts.length === 0) {
        return `<div class="action-empty" title="Нет реакции пользователя">
            <i class="fas fa-minus action-icon" aria-hidden="true"></i> 0
        </div>`;
    }

    return `<div class="actions">${parts.join('')}</div>`;
}

async function loadKpi(hours) {
    const data = await fetchJson(`/admin/analytics/kpi?hours=${hours}`);
    if (!data) return;
    const num = (n) => Number(n || 0).toLocaleString('ru-RU');

    document.getElementById('kpiSearches').textContent = num(data.searches);
    document.getElementById('kpiSearchesDelta').innerHTML = fmtDelta(data.searches, data.prev.searches);

    document.getElementById('kpiZeroPct').textContent = `${data.zero_result_pct}%`;
    document.getElementById('kpiZeroDelta').innerHTML = fmtDelta(data.zero_result_pct, data.prev.zero_result_pct, '%');

    document.getElementById('kpiLatency').textContent = `${data.p95_total_ms} / ${data.p50_total_ms}`;
    document.getElementById('kpiLatencyDelta').innerHTML = fmtDelta(data.avg_total_ms, data.prev.avg_total_ms, 'ms');

    document.getElementById('kpiUsers').textContent = num(data.unique_users);
    document.getElementById('kpiUsersDelta').textContent =
        `Сессий: ${num(data.unique_sessions)} · Ошибок: ${num(data.errors)}`;

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
    const meta = document.getElementById('analyticsRecentMeta');

    if (!data || !data.items?.length) {
        body.innerHTML = `<tr><td colspan="8" class="analytics-empty">
            <i class="fas fa-inbox" aria-hidden="true"></i> Записей не найдено
        </td></tr>`;
        if (meta) meta.textContent = `0 записей · окно ${hours}ч`;
        return;
    }
    if (meta) {
        meta.textContent = `${data.count} ${pluralize(data.count, 'запись', 'записи', 'записей')} · окно ${hours}ч`;
    }
    body.innerHTML = data.items
        .map((r) => {
            const ip = r.user_ip || '—';
            return `
            <tr>
                <td class="td-mono">${fmtTime(r.ts)}</td>
                <td><span class="mono" title="session: ${r.session_id || ''}">${ip}</span></td>
                <td>${escapeHtml(r.query || '')}</td>
                <td>${escapeHtml(r.collection || '')}</td>
                <td class="td-num">${r.candidates_count}</td>
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
    const meta = document.getElementById('analyticsZeroMeta');

    if (!data || !data.items?.length) {
        body.innerHTML = `<tr><td colspan="4" class="analytics-empty">
            <i class="fas fa-check-circle" aria-hidden="true"></i> Запросы без результатов не зафиксированы
        </td></tr>`;
        if (meta) meta.textContent = `0 · окно ${daysBack}д`;
        return;
    }
    if (meta) {
        meta.textContent = `${data.items.length} ${pluralize(data.items.length, 'запрос', 'запроса', 'запросов')} · окно ${daysBack}д`;
    }
    body.innerHTML = data.items
        .map((r) => `
        <tr>
            <td>${escapeHtml(r.query || '')}</td>
            <td class="td-num">${r.cnt}</td>
            <td class="td-num">${r.unique_users || 0}</td>
            <td class="td-mono">${fmtTime(r.last_seen)}</td>
        </tr>`)
        .join('');
}

async function loadSlow(hours) {
    const data = await fetchJson(
        `/admin/analytics/slow?hours=${hours}&limit=20&threshold_ms=${SLOW_THRESHOLD_MS}`
    );
    const body = document.getElementById('analyticsSlowBody');
    const meta = document.getElementById('analyticsSlowMeta');

    if (!data || !data.items?.length) {
        body.innerHTML = `<tr><td colspan="5" class="analytics-empty">
            <i class="fas fa-bolt" aria-hidden="true"></i> Запросы с превышением порога ${SLOW_THRESHOLD_MS}ms не зафиксированы
        </td></tr>`;
        if (meta) meta.textContent = `0 · порог ${SLOW_THRESHOLD_MS}ms · окно ${hours}ч`;
        return;
    }
    if (meta) {
        meta.textContent = `${data.items.length} ${pluralize(data.items.length, 'запрос', 'запроса', 'запросов')} · порог ${SLOW_THRESHOLD_MS}ms · окно ${hours}ч`;
    }
    body.innerHTML = data.items
        .map((r) => `
        <tr>
            <td class="td-mono">${fmtTime(r.ts)}</td>
            <td>${escapeHtml(r.query || '')}</td>
            <td class="td-num td-num--strong">${r.total_ms}</td>
            <td class="td-num">${r.rerank_ms || '—'}</td>
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

/** Русская плюрализация: 1 запись, 2 записи, 5 записей */
function pluralize(n, one, few, many) {
    const mod10 = n % 10;
    const mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
    return many;
}

async function refreshAll() {
    const hours = parseInt(document.getElementById('analyticsHours').value, 10) || 24;
    const daysBack = hours <= 24 ? 7 : hours <= 168 ? 30 : 90;
    const updated = document.getElementById('analyticsUpdated');
    updated.textContent = 'Обновление…';

    try {
        await Promise.all([loadKpi(hours), loadRecent(hours), loadZero(daysBack), loadSlow(hours)]);
        updated.textContent = `Обновлено: ${fmtTime(new Date().toISOString())}`;
    } catch (e) {
        updated.textContent = `Ошибка обновления: ${e.message}`;
        console.error('analytics refresh failed:', e);
    }
}

export function initAnalytics() {
    const refreshBtn = document.getElementById('analyticsRefreshBtn');
    const hoursSelect = document.getElementById('analyticsHours');
    if (refreshBtn) refreshBtn.addEventListener('click', refreshAll);
    if (hoursSelect) hoursSelect.addEventListener('change', refreshAll);

    document.addEventListener('analytics:view-shown', () => {
        refreshAll();
        if (_refreshTimer) clearInterval(_refreshTimer);
        _refreshTimer = setInterval(refreshAll, 30000);
    });
    document.addEventListener('analytics:view-hidden', () => {
        if (_refreshTimer) {
            clearInterval(_refreshTimer);
            _refreshTimer = null;
        }
    });
}
