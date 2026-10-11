from pathlib import Path


SUPPORTED_EXTENSIONS = {".md", ".txt"}


class DocumentReadError(Exception):
    """Error controlado durante la lectura de un documento SRS."""


def read_srs_document(file_path: str | Path) -> str:
    """Lee un documento SRS UTF-8 sin modificar el archivo original."""
    path = Path(file_path)

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise DocumentReadError(
            f"Formato no admitido: {path.suffix or 'sin extensión'}"
        )

    if not path.is_file():
        raise DocumentReadError(
            f"El archivo no existe o no es válido: {path}"
        )

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentReadError(
            f"Codificación UTF-8 inválida: {path}"
        ) from exc
    except OSError as exc:
        raise DocumentReadError(
            f"No se pudo leer el documento: {path}. Detalle: {exc}"
        ) from exc

    if not content.strip():
        raise DocumentReadError(
            f"El documento está vacío: {path}"
        )

    return content
