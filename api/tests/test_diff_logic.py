"""Unit-тесты Python-порта diff (app.utils.diff).

Покрывает:
  - normalize_text  (симметрично JS csv-parser.js:normalizeText)
  - analyze_changes (симметрично JS diff/analyze.js:analyzeChanges)

Чистый юнит, инфраструктура не нужна. Эти тесты — регрессионная защита
порта: если поменяешь JS-функции в csv-parser.js / analyze.js — обнови
ожидания здесь и в самом app/utils/diff.py.
"""
from __future__ import annotations

import pytest

from app.utils.diff import analyze_changes, normalize_text


class TestNormalizeText:
    """Симметрично web/static/js/admin/import/csv-parser.js:normalizeText."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # Базовые
            ("text", "text"),
            ("", ""),
            (None, ""),
            # Lowercase
            ("TEXT", "text"),
            ("TeXt", "text"),
            # Whitespace
            ("  text  ", "text"),
            ("text\twith\ttabs", "text with tabs"),
            ("text   with   spaces", "text with spaces"),
            # Line endings
            ("line1\nline2", "line1\nline2"),
            ("line1\r\nline2", "line1\nline2"),
            ("line1\rline2", "line1\nline2"),
            # Empty lines drop
            ("line1\n\nline2", "line1\nline2"),
            ("line1\n   \nline2", "line1\nline2"),
            # Trim each line
            ("  line1  \n  line2  ", "line1\nline2"),
            # Кавычки с краёв снимаются (stripSymmetricQuotes внутри)
            ("«TEXT»", "text"),
            ('"Text"', "text"),
        ],
    )
    def test_normalizations(self, raw, expected):
        assert normalize_text(raw) == expected

    def test_ksr_real_case(self):
        """Реальный кейс из скриншота: описание матча."""
        raw = "Агрегат электронасосный, тип X200-150-500, Q=315 м3/ч, H=80 м"
        out = normalize_text(raw)
        # Lowercase + схлопнутые пробелы
        assert out == out.lower()
        assert "  " not in out  # нет двойных пробелов


class TestAnalyzeChanges:
    """Симметрично web/static/js/admin/import/diff/analyze.js:analyzeChanges."""

    def test_identical_records_zero_modified(self):
        """Главный кейс бага: тот же набор → 0/0/0/N unchanged."""
        new = [
            {"code": "A.1", "description": "Material 1"},
            {"code": "A.2", "description": "Material 2"},
        ]
        existing = {
            "A.1": {"description": "Material 1", "full_description": "Material 1"},
            "A.2": {"description": "Material 2", "full_description": "Material 2"},
        }
        result = analyze_changes(new, existing)
        assert result["added"] == []
        assert result["modified"] == []
        assert result["deleted"] == []
        assert result["unchanged"] == 2

    def test_added_record(self):
        new = [{"code": "A.1", "description": "New"}]
        existing: dict = {}
        result = analyze_changes(new, existing)
        assert len(result["added"]) == 1
        assert result["added"][0]["code"] == "A.1"
        assert result["modified"] == []
        assert result["unchanged"] == 0

    def test_deleted_record(self):
        new: list = []
        existing = {"A.1": {"description": "Old", "full_description": "Old"}}
        result = analyze_changes(new, existing)
        assert result["added"] == []
        assert result["modified"] == []
        assert len(result["deleted"]) == 1
        assert result["deleted"][0]["code"] == "A.1"

    def test_modified_record(self):
        new = [{"code": "A.1", "description": "New description"}]
        existing = {"A.1": {"description": "Old description", "full_description": "Old description"}}
        result = analyze_changes(new, existing)
        assert result["added"] == []
        assert len(result["modified"]) == 1
        assert result["modified"][0]["code"] == "A.1"
        assert result["modified"][0]["oldDescription"] == "Old description"
        assert result["modified"][0]["newDescription"] == "New description"
        assert result["unchanged"] == 0

    def test_only_case_diff_not_modified(self):
        """Lowercase нормализация: TExt vs text → не изменение."""
        new = [{"code": "A.1", "description": "TEXT"}]
        existing = {"A.1": {"description": "text", "full_description": "text"}}
        result = analyze_changes(new, existing)
        assert result["modified"] == []
        assert result["unchanged"] == 1

    def test_only_whitespace_diff_not_modified(self):
        """Схлопывание пробелов: 'a  b' vs 'a b' → не изменение."""
        new = [{"code": "A.1", "description": "a  b\tc"}]
        existing = {"A.1": {"description": "a b c", "full_description": "a b c"}}
        result = analyze_changes(new, existing)
        assert result["modified"] == []
        assert result["unchanged"] == 1

    def test_quotes_diff_not_modified(self):
        """stripSymmetricQuotes на этапе normalize: '«X»' vs 'X' → не изменение."""
        new = [{"code": "A.1", "description": "Material"}]
        existing = {"A.1": {"description": "«Material»", "full_description": "«Material»"}}
        result = analyze_changes(new, existing)
        assert result["modified"] == []
        assert result["unchanged"] == 1

    def test_falls_back_to_full_description(self):
        """Если description пустое, берём full_description (как JS)."""
        new = [{"code": "A.1", "description": "Material"}]
        existing = {
            "A.1": {
                "description": "",
                "full_description": "Material",
            },
        }
        result = analyze_changes(new, existing)
        assert result["modified"] == []
        assert result["unchanged"] == 1

    def test_mixed_diff(self):
        """1 added, 1 modified, 1 deleted, 1 unchanged → все категории."""
        new = [
            {"code": "A.1", "description": "Material 1 NEW"},  # modified
            {"code": "A.2", "description": "Material 2"},  # unchanged
            {"code": "A.4", "description": "Material 4 NEW"},  # added
        ]
        existing = {
            "A.1": {"description": "Material 1", "full_description": "Material 1"},
            "A.2": {"description": "Material 2", "full_description": "Material 2"},
            "A.3": {"description": "Material 3", "full_description": "Material 3"},
        }
        result = analyze_changes(new, existing)
        assert len(result["added"]) == 1
        assert result["added"][0]["code"] == "A.4"
        assert len(result["modified"]) == 1
        assert result["modified"][0]["code"] == "A.1"
        assert len(result["deleted"]) == 1
        assert result["deleted"][0]["code"] == "A.3"
        assert result["unchanged"] == 1

    def test_existing_record_as_string(self):
        """getDescription в JS поддерживает string — мы тоже."""
        new = [{"code": "A.1", "description": "Material"}]
        existing = {"A.1": "Material"}  # type: ignore[dict-item]
        result = analyze_changes(new, existing)
        assert result["unchanged"] == 1
