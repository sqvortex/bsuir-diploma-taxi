"""
Проверка таблицы «требование → тест» из docs/test-cases.md:
каждое требование ТЗ ФТ-1…ФТ-18 имеет хотя бы один тест, и все названные тесты существуют.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "test-cases.md"


def doc_table():
    section = DOC.read_text(encoding="utf-8").split("## 2.")[0]
    rows = [line for line in section.splitlines() if line.startswith("| ") and "`test_" in line]
    return {line.split("|")[1].strip(): re.findall(r"`(test_\w+)`", line) for line in rows}


def existing_test_names():
    names = set()
    for path in (ROOT / "tests").glob("test_*.py"):
        names.update(re.findall(r"^\s*def (test_\w+)\(", path.read_text(encoding="utf-8"), flags=re.M))
    return names


def test_every_requirement_has_tests():
    table = doc_table()
    for number in range(1, 19):
        assert any(key.startswith(f"ФТ-{number} ") for key in table), f"ФТ-{number} нет в таблице испытаний"


def test_all_listed_tests_exist():
    existing = existing_test_names()
    missing = [name for names in doc_table().values() for name in names if name not in existing]
    assert not missing, f"в docs/test-cases.md названы несуществующие тесты: {missing}"
