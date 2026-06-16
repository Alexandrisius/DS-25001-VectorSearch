"""Unit-тесты для app.utils.text.

Покрывает strip_symmetric_quotes (Bug #2 — JS-асимметрия):
  - БЕЗ этого серверного эквивалента diff показывает 255 ложных
    "изменений" при повторной загрузке того же файла с «ёлочками».

Эти тесты — чистый юнит, инфраструктура не нужна.
"""
from __future__ import annotations

import pytest

from app.utils.text import strip_symmetric_quotes


class TestStripSymmetricQuotes:
    """Точный порт JS stripSymmetricQuotes (web/static/js/.../csv-parser.js)."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # Базовые случаи
            ('"text"', "text"),
            ("'text'", "text"),
            ("«text»", "text"),
            ('`text`', "text"),
            ('„text"', "text"),
            # Без кавычек — без изменений
            ("text", "text"),
            ("", ""),
            # Вложенные пары — снимаем послойно
            ('"«text»"', "text"),
            # Только с одной стороны — НЕ трогаем
            ('"text', '"text'),
            ("text»", "text»"),
            # Кавычки разного типа с обоих концов — НЕ трогаем
            ('"text»', '"text»'),
            # Whitespace + кавычки
            ('  "text"  ', "text"),
            (' «text» ', "text"),
        ],
    )
    def test_pairs(self, raw, expected):
        assert strip_symmetric_quotes(raw) == expected

    def test_none_returns_empty_string(self):
        assert strip_symmetric_quotes(None) == ""

    def test_single_char_returns_unchanged(self):
        """Один символ не может быть парой кавычек."""
        assert strip_symmetric_quotes('"') == '"'
        assert strip_symmetric_quotes("«") == "«"

    def test_recursive_stripping(self):
        """Снимаем кавычки до упора: «"внутри"» → внутри."""
        # '«"внутри"»' → '"внутри"' → 'внутри'
        assert strip_symmetric_quotes('«"внутри"»') == "внутри"

    def test_js_compatibility_real_kks_strings(self):
        """Реальные кейсы из КСР-выгрузки (русский, кириллица, цифры)."""
        # Описание с кириллицей и цифрами в «ёлочках»
        assert strip_symmetric_quotes('«Агрегат электронасосный X200»') == "Агрегат электронасосный X200"
        # Код в "лапках"
        assert strip_symmetric_quotes('"EX.68.1.02.02-0014.04"') == "EX.68.1.02.02-0014.04"

    def test_does_not_strip_internal_quotes(self):
        """Внутренние кавычки (между не-краями) не трогаем.

        Внешней пары кавычек нет — поэтому функция не должна ничего
        менять. Если же внешняя пара есть, она снимется (см. test_pairs).
        """
        # Нет внешней пары (открывающая " не закрыта) — без изменений
        assert strip_symmetric_quotes('a"b"c') == 'a"b"c'
        # Кавычки разного типа на краях — не пара, без изменений
        assert strip_symmetric_quotes('"text»') == '"text»'
        # Только внутренние кавычки, по краям — обычные символы
        assert strip_symmetric_quotes('A"B"C') == 'A"B"C'


class TestStripSymmetricQuotesJsEtherealParity:
    """Граничные кейсы, которые в JS-версии дают конкретный результат.

    Если меняешь strip_symmetric_quotes — обнови и эти ожидания,
    и синхронизируй с web/static/js/admin/import/csv-parser.js.
    """

    def test_paired_inner_quote_stripping(self):
        # «abc» — одна пара → abc
        assert strip_symmetric_quotes("«abc»") == "abc"

    def test_triple_nested_stripping(self):
        # '«"\'word\'"»' снимается послойно до 'word'
        assert strip_symmetric_quotes('«"\'word\'"»') == "word"
