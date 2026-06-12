/**
 * Drag-resize for the data table columns.
 *
 * Each <th> gets a `.th-resizer` child that, when dragged, adjusts
 * the column width. A single floating `.resize-line` element is
 * appended to <body> on first init to show the drag position.
 *
 * Widths are persisted in `state.columnWidths` (keyed by the column's
 * `data-sort` attribute, falling back to its index).
 */

import { state } from '../state.js';
import { persistColumnWidths } from '../state.js';

let resizeLine = null;

/**
 * Attach resizers to all the <th> cells. Safe to call multiple times —
 * it skips cells that already have a resizer.
 */
export function initColumnResize() {
    const table = document.getElementById('dataTable');
    if (!table) return;

    if (!resizeLine) {
        resizeLine = document.querySelector('.resize-line');
        if (!resizeLine) {
            resizeLine = document.createElement('div');
            resizeLine.className = 'resize-line';
            document.body.appendChild(resizeLine);
        }
    }

    const headerCells = table.querySelectorAll('thead th');

    headerCells.forEach((th, index) => {
        // No resizer on the last column (Действия).
        if (index === headerCells.length - 1) return;
        if (th.querySelector('.th-resizer')) return;

        const resizer = document.createElement('div');
        resizer.className = 'th-resizer';
        th.appendChild(resizer);

        // Restore saved width.
        const columnKey = th.dataset.sort || `col_${index}`;
        if (state.columnWidths[columnKey]) {
            th.style.width = state.columnWidths[columnKey] + 'px';
            th.style.minWidth = state.columnWidths[columnKey] + 'px';
        }

        let startX = 0;
        let startWidth = 0;

        resizer.addEventListener('mousedown', (e) => {
            e.preventDefault();
            e.stopPropagation();
            startX = e.pageX;
            startWidth = th.offsetWidth;

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
            const newWidth = Math.max(60, startWidth + diff);
            th.style.width = newWidth + 'px';
            th.style.minWidth = newWidth + 'px';

            const thRect = th.getBoundingClientRect();
            resizeLine.style.left = (thRect.right - 1) + 'px';
        }

        function onMouseUp() {
            resizeLine.classList.remove('visible');
            resizer.classList.remove('active');
            document.body.classList.remove('resizing-columns');

            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);

            const columnKey = th.dataset.sort || `col_${index}`;
            state.columnWidths[columnKey] = th.offsetWidth;
            persistColumnWidths();
        }
    });
}
