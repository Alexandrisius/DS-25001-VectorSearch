"""Генерация path_level_N из иерархического описания."""
from __future__ import annotations

from typing import Any

SEPARATOR = "→"
SEPARATOR_WITH_SPACES = " → "


def generate_path_levels(
    description: str,
    hierarchy: str | None = None,
    separator: str = SEPARATOR,
) -> dict[str, Any]:
    """Генерирует path_level_N из описания материала.

    Args:
        description: Полное описание материала ("Кран шаровой DN50").
        hierarchy: Явное указание категорий ("Арматура → Краны"). Если None — парсится из description.
        separator: Разделитель уровней.

    Returns:
        Словарь с полями:
        - path_level_1, path_level_2, ... — отдельные уровни категорий
        - path_depth — количество уровней категорий
        - full_description — название материала без категорий
        - context_description — конкатенация для эмбеддинга
    """
    if hierarchy and hierarchy != description:
        # Комбинированный режим: иерархия (папки) + описание (материал)
        category_parts = [p.strip() for p in hierarchy.split(separator) if p.strip()]
        full_description = description.strip()
    else:
        # Стандартный режим: всё из описания
        parts = [p.strip() for p in description.split(separator) if p.strip()]
        if not parts:
            return {
                "path_depth": 0,
                "full_description": description.strip(),
                "context_description": description.strip() or "пусто",
            }
        full_description = parts[-1]
        category_parts = parts[:-1]

    if not category_parts:
        context = full_description
    else:
        parts_to_join = category_parts + ([full_description] if full_description else [])
        context = f" {separator} ".join(p for p in parts_to_join if p)

    result: dict[str, Any] = {
        "path_depth": len(category_parts),
        "full_description": full_description,
        "context_description": context,
    }
    for i, part in enumerate(category_parts):
        result[f"path_level_{i + 1}"] = part
    return result


def build_full_path(path_levels: dict[str, Any], separator: str = SEPARATOR_WITH_SPACES) -> str:
    """Восстанавливает полный путь из path_level_N.

    Example:
        path_levels = {"path_level_1": "Арматура", "path_level_2": "Краны", "path_depth": 2}
        → "Арматура → Краны"
    """
    depth = path_levels.get("path_depth", 0)
    if not depth:
        return ""
    parts: list[str] = []
    for i in range(1, depth + 1):
        value = path_levels.get(f"path_level_{i}")
        if value:
            parts.append(value)
        else:
            break
    return separator.join(parts)


def extract_folders_from_records(
    records: list[dict[str, Any]],
    separator: str = SEPARATOR,
) -> list[dict[str, Any]]:
    """Извлечь уникальные папки из списка path_levels материалов.

    Returns:
        Список словарей {full_path, leaf_name, level, items_count, path_levels}.
    """
    folder_counts: dict[tuple, dict[str, Any]] = {}

    for pl in records:
        depth = pl.get("path_depth", 0)
        if depth == 0:
            continue
        path_parts: list[str] = []
        for level in range(1, depth + 1):
            value = pl.get(f"path_level_{level}")
            if value:
                path_parts.append(value)
            else:
                break

        total_levels = len(path_parts)
        for level in range(1, total_levels + 1):
            current_parts = tuple(path_parts[:level])
            if current_parts not in folder_counts:
                folder_counts[current_parts] = {"count": 0, "parts": list(current_parts)}
            if level == total_levels:
                folder_counts[current_parts]["count"] += 1

    folders: list[dict[str, Any]] = []
    for path_tuple, data in folder_counts.items():
        parts = data["parts"]
        full_path = f" {separator} ".join(parts)
        path_levels = {f"path_level_{i + 1}": p for i, p in enumerate(parts)}
        folders.append(
            {
                "full_path": full_path,
                "leaf_name": parts[-1] if parts else "",
                "level": len(parts),
                "items_count": data["count"],
                "path_levels": path_levels,
            }
        )
    folders.sort(key=lambda x: (x["level"], x["full_path"]))
    return folders


__all__ = [
    "SEPARATOR",
    "SEPARATOR_WITH_SPACES",
    "generate_path_levels",
    "build_full_path",
    "extract_folders_from_records",
]
