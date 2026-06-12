/**
 * Catalog sidebar: composition root.
 *
 * Wires the sidebar plumbing on bootstrap. The toggle/resize lives
 * in sidebar-toggle.js; the refresh/collapse buttons in
 * sidebar-controls.js. This file is just the public entry point.
 */

export {
    initCatalogSidebar,
    toggleSidebar,
    applySidebarWidth,
    updateToggleButton,
} from './sidebar-toggle.js';

export { collapseAllTreeNodes, refreshCatalog } from './sidebar-controls.js';
