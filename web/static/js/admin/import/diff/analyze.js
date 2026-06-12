/**
 * Diff analyzers.
 *
 * Two kinds of diff are produced:
 *   1. Material diff: per-code record (added / modified / deleted / unchanged)
 *   2. Folder diff: per-hierarchy-path (added / modified / deleted)
 *
 * The folder diff is built from the materials themselves (re-deriving
 * the hierarchy by joining `path_level_N` fields) rather than from a
 * separate /get_all_folders endpoint, which in the past returned
 * incomplete data for collections imported before the `is_folder` flag
 * was added.
 */

import { normalizeText } from '../csv-parser.js';

/**
 * Material-level diff.
 *
 * @param {Array<{code: string, description: string}>} newRecords
 * @param {Object} existingRecords - {code: {description, full_description, ...}}
 * @returns {{added: Object[], modified: Object[], deleted: Object[], unchanged: number}}
 */
export function analyzeChanges(newRecords, existingRecords) {
    const result = { added: [], modified: [], deleted: [], unchanged: 0 };

    const newCodes = new Set(newRecords.map((r) => r.code));
    const existingCodes = new Set(Object.keys(existingRecords));

    const getDescription = (record) => {
        if (typeof record === 'string') return record;
        return record?.description || record?.full_description || '';
    };

    // Added
    newRecords.forEach((record) => {
        if (!existingCodes.has(record.code)) result.added.push(record);
    });

    // Modified / unchanged
    newRecords.forEach((record) => {
        if (existingCodes.has(record.code)) {
            const oldDesc = getDescription(existingRecords[record.code]);
            const newDesc = record.description || '';
            if (normalizeText(oldDesc) !== normalizeText(newDesc)) {
                result.modified.push({
                    code: record.code,
                    oldDescription: oldDesc,
                    newDescription: record.description,
                    hierarchy: record.hierarchy,
                });
            } else {
                result.unchanged++;
            }
        }
    });

    // Deleted
    existingCodes.forEach((code) => {
        if (!newCodes.has(code)) {
            result.deleted.push({
                code,
                description: getDescription(existingRecords[code]),
            });
        }
    });

    console.log(`📊 Анализ изменений: +${result.added.length} добавлено, ~${result.modified.length} изменено, -${result.deleted.length} удалено, =${result.unchanged} без изменений`);
    return result;
}

/**
 * Extract folders from materials by walking each material's hierarchy
 * path. The result is keyed by `full_path` with the leaf_name and
 * count of materials at that path.
 *
 * @param {Array<Object>} records - materials with `hierarchy` field
 * @returns {Object} - {full_path: {full_path, leaf_name, items_count, level}}
 */
export function extractFoldersFromRecords(records) {
    const folderMap = {};

    records.forEach((record) => {
        const hierarchy = record.hierarchy || '';
        if (!hierarchy) return;

        const parts = hierarchy.split(' → ').map((p) => p.trim()).filter(Boolean);

        let currentPath = '';
        parts.forEach((part, idx) => {
            currentPath = idx === 0 ? part : currentPath + ' → ' + part;

            if (!folderMap[currentPath]) {
                folderMap[currentPath] = {
                    full_path: currentPath,
                    leaf_name: part,
                    items_count: 0,
                    level: idx + 1,
                };
            }
            if (idx === parts.length - 1) folderMap[currentPath].items_count++;
        });
    });

    return folderMap;
}

/**
 * Normalize a hierarchy path: trim each part, drop empties, rejoin
 * with the canonical " → " separator.
 *
 * @param {string} path
 * @returns {string}
 */
export function normalizePath(path) {
    if (!path) return '';
    return path.split(' → ').map((p) => p.trim()).filter(Boolean).join(' → ');
}

/**
 * Folder-level diff.
 *
 * @param {Array<Object>} newRecords
 * @param {Object} existingFolders - {full_path: {leaf_name, items_count}}
 * @returns {{added: Object[], modified: Object[], deleted: Object[]}}
 */
export function analyzeFolderChanges(newRecords, existingFolders) {
    const result = { added: [], modified: [], deleted: [] };

    const newFolders = extractFoldersFromRecords(newRecords);
    const existingPaths = new Set(Object.keys(existingFolders).map(normalizePath));
    const newPaths = Object.keys(newFolders);

    // Only leaf folders (those that contain materials) become "added".
    const leafFolderPaths = newPaths.filter((p) => newFolders[p].items_count > 0);

    // Added
    leafFolderPaths.forEach((rawPath) => {
        const path = normalizePath(rawPath);
        if (!existingPaths.has(path)) {
            const folderData = newFolders[rawPath];
            result.added.push({
                full_path: rawPath,
                leaf_name: folderData.leaf_name,
                items_count: folderData.items_count,
                level: folderData.level,
            });
        }
    });

    // Deleted
    const newPathsSet = new Set(newPaths.map(normalizePath));
    Object.keys(existingFolders).forEach((rawExistingPath) => {
        const path = normalizePath(rawExistingPath);
        if (!newPathsSet.has(path)) {
            const folderData = existingFolders[rawExistingPath];
            const leafName = folderData.leaf_name || path.split(' → ').pop();
            result.deleted.push({
                full_path: rawExistingPath,
                leaf_name: leafName,
                items_count: folderData.items_count || 0,
            });
        }
    });

    result.added.sort((a, b) => a.level - b.level || a.full_path.localeCompare(b.full_path));
    result.deleted.sort((a, b) => a.full_path.localeCompare(b.full_path));

    return result;
}
