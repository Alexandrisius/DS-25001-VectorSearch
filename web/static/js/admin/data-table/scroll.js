/**
 * Infinite-scroll loader for the data table.
 *
 * Uses an IntersectionObserver against the sentinel element. When the
 * sentinel enters the visible region of `.data-table-scroll`, more
 * rows are fetched from the server and appended.
 *
 * loadData() is also called directly when the user switches into the
 * data view (see collections/list.js).
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { authFetch } from '../../shared/api.js';
import { DATA_TABLE_PAGE_SIZE } from '../../shared/constants.js';
import { renderDataTable, extractPathLevelColumns } from './render.js';

/**
 * Fetch the next page of rows. Called by:
 *   - the IntersectionObserver when the sentinel scrolls into view
 *   - collections/list.js when entering the data view
 *
 * Guarded by state.isLoadingData so a fast scroll can't trigger two
 * requests in flight.
 */
export async function loadData() {
    if (!state.activeCollection || state.isLoadingData) return;

    state.isLoadingData = true;
    showInfiniteScrollLoader(true);

    try {
        const offsetQuery = state.dataOffset ? `&offset=${state.dataOffset}` : '';
        const res = await authFetch(
            `/admin/collections/${state.activeCollection}/data?limit=${DATA_TABLE_PAGE_SIZE}${offsetQuery}`,
        );
        const result = await res.json();

        state.dataOffset = result.next_offset;

        if (result.data.length === 0 && state.dataRows.length === 0) {
            if (els.dataTableBody) {
                els.dataTableBody.innerHTML =
                    '<tr><td colspan="10" style="text-align:center; padding:30px; color:var(--adm-text-sec)">Записей не найдено. Добавьте новые!</td></tr>';
            }
        } else {
            state.dataRows = state.dataRows.concat(result.data);

            // Resolve the path-level column set on the first non-empty
            // page so we know how many columns the table needs.
            if (result.data.length > 0 && state.pathLevelColumns.length === 0) {
                const serverMaxDepth = result.max_path_depth || 0;
                extractPathLevelColumns(result.data[0], serverMaxDepth);
            }

            renderDataTable();
        }

        if (!state.dataOffset) stopInfiniteScroll();
    } catch (e) {
        // 'Failed to fetch' is what we get when the user navigates away
        // (or the table gets re-rendered) while a load is in flight.
        // That's a normal SPA-race, not a server error — don't log it.
        if (e.message === 'Unauthorized') return;
        if (e.message?.includes('Failed to fetch')) return;
        console.error('Failed to load data:', e);
    } finally {
        state.isLoadingData = false;
        showInfiniteScrollLoader(false);
    }
}

/**
 * Show or hide the spinner rendered below the table.
 */
export function showInfiniteScrollLoader(show) {
    const loader = document.getElementById('infiniteScrollLoader');
    if (loader) loader.classList.toggle('hidden', !show);
}

/**
 * Start observing the sentinel. The previous observer is torn down
 * first so re-entering the data view doesn't stack observers.
 */
export function initInfiniteScroll() {
    stopInfiniteScroll();

    const sentinel = document.getElementById('scrollSentinel');
    if (!sentinel) return;

    state.scrollObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting && state.dataOffset && !state.isLoadingData) {
                loadData();
            }
        });
    }, {
        root: document.querySelector('.data-table-scroll'),
        rootMargin: '100px',
        threshold: 0,
    });

    state.scrollObserver.observe(sentinel);
}

/**
 * Stop observing. Called when the server indicates there are no more
 * pages, or when the data view is left.
 */
export function stopInfiniteScroll() {
    if (state.scrollObserver) {
        state.scrollObserver.disconnect();
        state.scrollObserver = null;
    }
}
