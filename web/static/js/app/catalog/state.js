/**
 * Catalog-only state (loaded paths, in-flight flag, sticky-breadcrumb
 * hysteresis key). Lives in its own module so the top-level
 * app/state.js doesn't need to know about tree internals.
 *
 * NOTE: the previous code used `let loadedPaths` etc. directly inside
 * the DOMContentLoaded closure; here we wrap them in a single
 * catalogState proxy so other catalog modules can read/write them
 * without each having to set up its own closures.
 */

const loadedPaths = new Set();
let isHierarchyLoading = false;
let lastStickyPath = null;

export const catalogState = {
    get loadedPaths() { return loadedPaths; },
    get isHierarchyLoading() { return isHierarchyLoading; },
    set isHierarchyLoading(v) { isHierarchyLoading = v; },
    get lastStickyPath() { return lastStickyPath; },
    set lastStickyPath(v) { lastStickyPath = v; },
};
