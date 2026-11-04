
Evalúa el cumplimiento del siguiente requisito funcional utilizando
únicamente la evidencia de código proporcionada.

REQUISITO FUNCIONAL

Identificador: {requirement_id}

Descripción:
{requirement}

EVIDENCIA DE CÓDIGO RECUPERADA MEDIANTE SBERT

{evidence}

INSTRUCCIONES DE EVALUACIÓN

1. Analiza el comportamiento implementado en los fragmentos de código.
2. Determina si dicho comportamiento satisface el requisito funcional.
3. No consideres la similitud semántica como prueba de cumplimiento.
4. Identifica las funciones, condiciones o instrucciones que sustentan tu evaluación.
5. Si la evidencia no permite establecer una conclusión, utiliza "evidencia_insuficiente".
6. Si existe evidencia explícita de una implementación incorrecta, utiliza "no_cumple".
7. No inventes código, pruebas ni comportamientos no observados.

Devuelve exclusivamente un objeto JSON válido con esta estructura:

{{
  "status": "cumple",
  "justification": "Justificación técnica en español, sustentada en los fragmentos de código proporcionados."
}}

El campo "status" debe ser exactamente uno de los siguientes:
"cumple", "no_cumple" o "evidencia_insuficiente".

No agregues texto fuera del JSON.