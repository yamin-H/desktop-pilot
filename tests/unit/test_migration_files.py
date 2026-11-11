from pathlib import Path

import pytest

from deskpilot.storage.migrate import MIGRATIONS_DIR, MigrationError, load_migrations


def write(directory: Path, name: str, sql: str = "SELECT 1;") -> None:
    (directory / name).write_text(sql, encoding="utf-8")


def test_empty_folder_gives_no_migrations(tmp_path):
    assert load_migrations(tmp_path) == []


def test_files_are_loaded_in_number_order(tmp_path):
    write(tmp_path, "002_second.sql")
    write(tmp_path, "001_first.sql")
    assert [m.name for m in load_migrations(tmp_path)] == ["001_first.sql", "002_second.sql"]


@pytest.mark.parametrize(
    "name", ["create_table.sql", "1_short.sql", "002_Upper.sql", "003-dash.sql"]
)
def test_bad_file_names_are_rejected(tmp_path, name):
    write(tmp_path, name)
    with pytest.raises(MigrationError):
        load_migrations(tmp_path)


def test_two_files_with_the_same_number_are_rejected(tmp_path):
    write(tmp_path, "001_a.sql")
    write(tmp_path, "001_b.sql")
    with pytest.raises(MigrationError, match="share number"):
        load_migrations(tmp_path)


def test_checksum_ignores_windows_line_endings(tmp_path):
    (tmp_path / "001_a.sql").write_bytes(b"SELECT 1;\nSELECT 2;\n")
    unix = load_migrations(tmp_path)[0]
    (tmp_path / "001_a.sql").write_bytes(b"SELECT 1;\r\nSELECT 2;\r\n")
    windows = load_migrations(tmp_path)[0]
    assert unix.checksum == windows.checksum


def test_the_real_migration_files_are_valid():
    names = [m.name for m in load_migrations(MIGRATIONS_DIR)]
    assert names == sorted(names)
