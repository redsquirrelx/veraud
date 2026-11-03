import type { ExecutionEvent } from "./executionEventsApi.ts"

const kinds: Record<string, { es: [string, string], en: [string, string] }> = {
  "execution.started": { es: ["Inicio de ejecución", "Se abrió el contexto de ejecución de la auditoría."], en: ["Execution started", "The audit execution context was opened."] },
  "execution.finished": { es: ["Cierre de ejecución", "Se cerró el contexto de ejecución. Consulta el estado registrado; este cierre no garantiza un resultado completo de la auditoría."], en: ["Execution closed", "The execution context was closed. Check the recorded status; closing does not guarantee a complete audit result."] },
  "invocation.started": { es: ["Inicio de invocación del agente", "El agente comenzó una nueva invocación, independiente de sus invocaciones anteriores."], en: ["Agent invocation started", "The agent began a new invocation, separate from its previous invocations."] },
  "invocation.finished": { es: ["Fin de invocación del agente", "El agente terminó esta invocación con el estado indicado."], en: ["Agent invocation ended", "The agent ended this invocation with the recorded status."] },
  "phase.changed": { es: ["Entrada en fase", "La invocación entró en esta fase de trabajo; una misma fase puede repetirse."], en: ["Phase entered", "The invocation entered this work phase; the same phase may repeat."] },
  "node.started": { es: ["Inicio de paso del grafo", "Comenzó un nodo o una operación interna instrumentada del grafo de ejecución."], en: ["Graph step started", "An instrumented graph node or internal operation started."] },
  "node.finished": { es: ["Fin de paso del grafo", "Terminó un nodo o una operación interna del grafo con el estado indicado."], en: ["Graph step ended", "A graph node or internal operation ended with the recorded status."] },
  "tool.started": { es: ["Inicio de intento de herramienta", "Se inició un intento de usar esta herramienta; aún puede ser rechazado antes de ejecutarse."], en: ["Tool attempt started", "An attempt to use this tool started; it may still be rejected before execution."] },
  "tool.finished": { es: ["Fin de intento de herramienta", "El intento terminó con el estado indicado. Un rechazo no significa que la herramienta haya llegado a ejecutarse."], en: ["Tool attempt ended", "The attempt ended with the recorded status. Rejection does not mean the tool was executed."] },
  "model.started": { es: ["Inicio de llamada al modelo", "Comenzó una llamada al modelo de lenguaje, que puede incluir esperas y reintentos del proveedor."], en: ["Model call started", "A language-model call started; it may include provider waits and retries."] },
  "model.finished": { es: ["Fin de llamada al modelo", "La llamada al modelo terminó con el estado indicado. Los tokens se muestran solo si quedaron registrados."], en: ["Model call ended", "The model call ended with the recorded status. Tokens are shown only when recorded."] },
  "provider.request": { es: ["Intento de solicitud al proveedor", "Se inició un intento de enviar la solicitud al proveedor del modelo."], en: ["Provider request attempt", "An attempt to send the request to the model provider started."] },
  "provider.retry": { es: ["Reintento programado", "Se programó un nuevo intento tras un problema con el proveedor; esto no confirma que el reintento haya terminado."], en: ["Retry scheduled", "A new attempt was scheduled after a provider issue; this does not confirm that the retry finished."] },
  "provider.wait": { es: ["Espera antes de solicitar al proveedor", "Se registró una espera previa a otro intento de solicitud al proveedor."], en: ["Waiting before provider request", "A wait was recorded before another provider request attempt."] },
  "provider.error": { es: ["Error en intento del proveedor", "Un intento de solicitud falló. Puede haber recuperación posterior; no implica por sí solo el fallo de toda la auditoría."], en: ["Provider attempt error", "A request attempt failed. It may recover later; this alone does not mean the whole audit failed."] },
  "provider.retry_skipped": { es: ["Reintento omitido", "No se admitió otro reintento según las restricciones de recuperación de la ejecución."], en: ["Retry skipped", "Another retry was not admitted under the execution recovery constraints."] },
  "activity.started": { es: ["Inicio de actividad medida", "Comenzó una actividad cuyo tiempo se mide durante la ejecución."], en: ["Timed activity started", "An activity whose duration is measured during execution started."] },
  "activity.finished": { es: ["Fin de actividad medida", "La actividad medida terminó con el estado indicado."], en: ["Timed activity ended", "The timed activity ended with the recorded status."] },
  "wait.started": { es: ["Inicio de espera", "La ejecución comenzó a esperar por un límite de cuota o por el espaciado de solicitudes."], en: ["Wait started", "The execution started waiting for quota admission or request pacing."] },
  "wait.finished": { es: ["Fin de espera", "La espera terminó con el estado indicado; no confirma el éxito de una solicitud posterior."], en: ["Wait ended", "The wait ended with the recorded status; it does not confirm success of a later request."] },
  "publication.created": { es: ["Registro publicado", "Se publicó un registro en el conocimiento compartido de la auditoría; su publicación no implica que un hallazgo esté verificado."], en: ["Record published", "A record was published in the audit's shared knowledge; publication does not imply a verified finding."] },
  "audit.state_changed": { es: ["Cambio de estado de auditoría", "La auditoría pasó al estado indicado en este evento."], en: ["Audit state changed", "The audit moved to the status recorded in this event."] },
}

const operations: Record<string, [string, string]> = {
  list_files: ["Listar archivos", "List files"], find_symbols: ["Buscar símbolos", "Find symbols"],
  get_source_excerpt: ["Leer fragmento de código", "Read source excerpt"], list_relationships: ["Consultar relaciones", "List relationships"],
  get_infrastructure: ["Consultar infraestructura", "Read infrastructure"], search_repository_text: ["Buscar texto en el repositorio", "Search repository text"],
  get_evidence: ["Consultar evidencia", "Read evidence"], unknown_tool: ["Herramienta no reconocida", "Unrecognized tool"],
  chat_model: ["Modelo de conversación", "Chat model"], text_model: ["Modelo de texto", "Text model"], model_gateway: ["Pasarela compartida del modelo", "Shared model gateway"],
  provider_backoff: ["Pausa entre reintentos", "Retry backoff"], provider_pacing: ["Espaciado de solicitudes", "Request pacing"], quota_admission: ["Admisión por cuota", "Quota admission"],
  plan_investigation: ["Planificar investigación", "Plan investigation"], investigate: ["Investigar", "Investigate"],
  evaluate_evidence: ["Evaluar evidencia", "Evaluate evidence"], review_findings: ["Revisar hallazgos", "Review findings"], finalize: ["Finalizar", "Finalize"],
  Finding: ["Hallazgo", "Finding"], Evidence: ["Evidencia", "Evidence"], Assessment: ["Evaluación", "Assessment"],
}

export const eventMetricLabels: Record<string, [string, string]> = {
  seconds: ["Duración (s)", "Duration (s)"], wait_seconds: ["Espera (s)", "Wait (s)"], delay_seconds: ["Demora programada (s)", "Scheduled delay (s)"],
  attempt: ["Intento", "Attempt"], attempts: ["Intentos", "Attempts"], retry: ["Reintento", "Retry"], http_status: ["Estado HTTP", "HTTP status"],
  input_tokens: ["Tokens de entrada", "Input tokens"], output_tokens: ["Tokens de salida", "Output tokens"], estimated_tokens: ["Tokens estimados", "Estimated tokens"],
  cache_hit: ["Resultado en caché", "Cache hit"], phase_sequence: ["Número de entrada en fase", "Phase entry number"],
}

/** Presentation only: no inferred success, error text, tool arguments or transcripts. */
export function executionEventPresentation(event: ExecutionEvent, language: "es" | "en", names: Map<string, string>) {
  const index = language === "es" ? 0 : 1
  const [title, description] = kinds[event.kind]?.[language] ?? (language === "es"
    ? ["Evento de ejecución", "Tipo de evento sin descripción disponible."] : ["Execution event", "No description is available for this event type."])
  const name = event.name ?? (event.kind.startsWith("invocation.") ? event.agentId : null)
  const operation = name ? (event.kind.startsWith("invocation.") ? names.get(name) : undefined)
    ?? operations[name]?.[index] ?? name : null
  return { title: operation ? `${title}: ${operation}` : title, description, operation: name }
}
