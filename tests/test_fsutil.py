from pathlib import Path

from behance_studio.core.fsutil import (
    atomic_write_json,
    read_json,
    read_text_file,
    safe_filename,
    unique_path,
)


def test_safe_filename_windows_rules():
    assert safe_filename('a<b>c:"d/e\\f|g?h*') == "a_b_c__d_e_f_g_h_"
    assert safe_filename("CON") == "_CON"
    assert safe_filename("nul.txt") == "_nul.txt"
    assert safe_filename("name. ") == "name"
    assert safe_filename("   ") == "untitled"
    # Unicode and accents are preserved.
    assert safe_filename("Café Açúcar — 日本") == "Café Açúcar — 日本"


def test_unique_path(tmp_path: Path):
    p = tmp_path / "file.txt"
    assert unique_path(p) == p
    p.write_text("x")
    assert unique_path(p).name == "file (2).txt"
    (tmp_path / "file (2).txt").write_text("x")
    assert unique_path(p).name == "file (3).txt"


def test_atomic_json_roundtrip(tmp_path: Path):
    target = tmp_path / "sub" / "data.json"
    atomic_write_json(target, {"name": "Butter & Bean", "ç": [1, 2]})
    assert read_json(target) == {"name": "Butter & Bean", "ç": [1, 2]}
    assert not list(target.parent.glob("*.tmp"))


def test_read_text_encodings(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_bytes("Olá mundo".encode("utf-8-sig"))
    assert read_text_file(f) == "Olá mundo"
    f.write_bytes("Olá mundo".encode("utf-16"))
    assert read_text_file(f) == "Olá mundo"
    f.write_bytes("Olá mundo".encode("cp1252"))
    assert read_text_file(f) == "Olá mundo"
