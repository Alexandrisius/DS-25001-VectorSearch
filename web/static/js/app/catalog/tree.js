/**
 * Catalog tree: lazy-loaded hierarchy, node rendering, click handlers.
 *
 * Split out of the original tree.js (215 LoC) for module size
 * management:
 *   - tree-loader.js   — loadHierarchy() + loadChildren() (network)
 *   - tree-renderer.js — renderTreeLazy() + renderTreeNodesLazy() (DOM)
 *   - tree.js (this)   — composition + attachTreeEventHandlers()
 *
 * The previous code had a non-lazy `renderTree(tree)` that is no
 * longer reachable from anywhere — the lazy variant covers every
 * entry point.
 */

import { els } from '../els.js';
import { catalogState } from '../state.js';
import { loadChildren, loadHierarchy } from './tree-loader.js';
import { renderTreeLazy, renderTreeNodesLazy } from './tree-renderer.js';
import {
    attachSingleNodeHandler,
    attachTreeEventHandlersForContainer,
} from './tree-handlers.js';

export {
    loadChildren,
    loadHierarchy,
    renderTreeLazy,
    renderTreeNodesLazy,
    attachSingleNodeHandler,
    attachTreeEventHandlersForContainer,
};

/**
 * Attach click / long-press / touch handlers to all current tree
 * headers. Called after a render of the top-level tree.
 */
export function attachTreeEventHandlers() {
    document.querySelectorAll('.tree-node-header').forEach((header) => {
        attachSingleNodeHandler(header);
    });
}
