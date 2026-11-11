"""Functional finding projections for the existing audit inspector contracts."""

from .exploratory import is_stub_capability


def exploratory_details(result, capability):
    """Describe observed functional implications, without claiming verified defects."""
    scope = {
        "completitud": "disponibilidad de la funcionalidad",
        "correccion": "fiabilidad de los resultados funcionales",
        "pertinencia": "relación de la capacidad con los flujos de uso",
    }[result.attribute]
    impact = (
        f"Evaluación de la {scope} de '{result.capability_name}': "
        f"{result.justification} La clasificación '{result.classification}' es estática; "
        "no demuestra un defecto ni garantiza cumplimiento funcional."
    )
    name = result.capability_name
    if not result.evidence:
        recommendation = (
            f"Localizar y conservar evidencia de implementación de '{name}' antes de concluir "
            "si requiere una corrección; contrastarla con el requisito y sus criterios de aceptación."
        )
    elif result.attribute == "pertinencia":
        recommendation = (
            f"Vincular '{name}' con un objetivo de usuario documentado y verificar su uso "
            "desde un punto de entrada real; no eliminar la capacidad solo por evidencia estática insuficiente."
        )
    elif capability is not None and is_stub_capability(capability):
        recommendation = (
            f"Completar la implementación esqueleto de '{name}' según el comportamiento esperado "
            "y añadir una prueba funcional con entradas y resultados verificables."
        )
    elif capability is not None and capability.calls and result.classification != "confirmado":
        targets = ", ".join(dict.fromkeys(call.target_symbol for call in capability.calls))
        recommendation = (
            f"Revisar las llamadas resueltas de '{name}' ({targets}) y la cadena citada en la evidencia; "
            "completar las implementaciones esqueleto si las hay y probar el flujo completo "
            "contra el resultado esperado."
        )
    elif result.attribute == "completitud":
        recommendation = (
            f"Contrastar '{name}' con las tareas y criterios de aceptación del requisito, "
            "y probar los escenarios faltantes. La presencia de código no demuestra completitud funcional."
        )
    else:
        recommendation = (
            f"Validar '{name}' con pruebas que comparen resultados observados y esperados, "
            "incluyendo casos límite y errores. No hay una corrección concreta demostrada por este análisis estático."
        )
    return impact, recommendation


def requirement_details(result):
    """Keep semantic judgments distinct from executed functional verification."""
    impact = (
        f"Requisito {result.requirement_id}: {result.description} "
        f"Evaluación: {result.status}. {result.justification} "
        "Es un juicio sobre evidencia recuperada, no una prueba funcional ejecutada."
    )
    action = {
        "cumple": "Validar la implementación citada mediante pruebas de aceptación; no se propone una corrección sin un defecto demostrado.",
        "no_cumple": "Revisar la discrepancia descrita en la justificación, ajustar la implementación al requisito y añadir una prueba de aceptación que reproduzca el caso.",
        "evidencia_insuficiente": "Completar la evidencia o resolver las limitaciones de verificación antes de modificar código; definir entradas y resultados esperados y ejecutar una prueba de aceptación.",
    }[result.status]
    return impact, f"{result.requirement_id}: {action}"


LABELS = {"definition": "Definición", "mapping": "Correspondencia", "mention": "Mención"}


def documentary_references(references, files):
    """Project only real Markdown ranges from the retained audit snapshot."""
    projected = []
    seen = set()
    for reference in references:
        source = files.get(reference.document_path)
        if (source is None or source.language != "markdown"
                or source.status != "processed" or not source.content):
            continue
        lines = source.content.splitlines()
        if not 1 <= reference.start_line <= reference.end_line <= len(lines):
            continue
        key = (reference.requirement_id, reference.document_path, reference.start_line, reference.end_line)
        if key in seen:
            continue
        seen.add(key)
        quote = "\n".join(lines[reference.start_line - 1:reference.end_line])
        label = LABELS.get(reference.reference_kind, reference.reference_kind)
        projected.append({
            "subject": reference.requirement_id,
            "statement": f"{reference.title} ({label})" if reference.title else label,
            "constraint": "unspecified",
            "certainty": "unknown",
            "category": reference.reference_kind,
            "quotes": [{"path": reference.document_path, "start_line": reference.start_line,
                "end_line": reference.end_line, "quote": quote}],
        })
    return projected
