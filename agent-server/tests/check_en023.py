import hashlib
import tempfile
from pathlib import Path

from server.services.functional_adequacy.document_reader import (
    DocumentReadError,
    read_srs_document,
)


def check(name, action, expected_error=False):
    try:
        action()
        if expected_error:
            raise AssertionError("Se esperaba DocumentReadError")
        print(f"[PASS] {name}")
    except DocumentReadError:
        if not expected_error:
            raise
        print(f"[PASS] {name}: error controlado")


with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)

    md = root / "requisitos.md"
    md.write_text("# SRS\nRF-01: Registrar usuario", encoding="utf-8")

    txt = root / "requisitos.txt"
    txt.write_text("RF-02: Consultar usuario", encoding="utf-8")

    empty = root / "vacio.md"
    empty.write_text("  \n", encoding="utf-8")

    invalid_extension = root / "requisitos.pdf"
    invalid_extension.write_text("Contenido de prueba", encoding="utf-8")

    invalid_utf8 = root / "invalido.txt"
    invalid_utf8.write_bytes(b"\xff\xfe\xfa")

    assert read_srs_document(md) == "# SRS\nRF-01: Registrar usuario"
    print("[PASS] P01 Markdown válido")

    assert read_srs_document(txt) == "RF-02: Consultar usuario"
    print("[PASS] P02 TXT válido")

    check("P03 Archivo vacío", lambda: read_srs_document(empty), True)
    check(
        "P04 Archivo inexistente",
        lambda: read_srs_document(root / "no_existe.md"),
        True,
    )
    check(
        "P05 Extensión no admitida",
        lambda: read_srs_document(invalid_extension),
        True,
    )
    check(
        "P06 UTF-8 inválido",
        lambda: read_srs_document(invalid_utf8),
        True,
    )

    before = hashlib.sha256(md.read_bytes()).hexdigest()
    read_srs_document(md)
    after = hashlib.sha256(md.read_bytes()).hexdigest()

    assert before == after
    print("[PASS] P07 Documento original sin modificaciones")

print("\nEN-023: 7 comprobaciones superadas.")
