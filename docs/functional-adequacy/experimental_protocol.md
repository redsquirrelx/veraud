
# EN-024 — Selección de repositorios y protocolo experimental

## 1. Objetivo

Definir un protocolo experimental reproducible para evaluar la capacidad del componente de adecuación funcional de localizar implementaciones relacionadas con requisitos funcionales en repositorios de software reales.

## 2. Criterios de selección

Los repositorios deberán cumplir los siguientes criterios:

- Ser públicos y tener código fuente accesible.
- Contar con documentación de funcionalidades o requisitos verificables.
- Tener una versión o commit identificable.
- Contener funciones o módulos que puedan relacionarse con requisitos funcionales.
- Permitir la revisión de evidencias mediante código o pruebas.
- Tener una licencia que permita el uso previsto del código y respetar sus condiciones.

## 3. Criterios de exclusión

- Repositorios sin documentación funcional suficiente.
- Proyectos compuestos principalmente por archivos generados.
- Repositorios que no permitan identificar funcionalidades concretas.
- Proyectos cuyo código no pueda analizarse con las herramientas disponibles.

## 4. Repositorios candidatos

| ID | Repositorio | Lenguaje | Documentación | Pruebas | Estado |
|---|---|---|---|---|---|
| REP-001 | FastAPI (fastapi/fastapi) | Python | Sí | Sí, 2 pruebas ejecutadas | Seleccionado provisionalmente |
| REP-002 | Flask (pallets/flask) | Python | Sí | Sí, 1 prueba ejecutada | Seleccionado provisionalmente | 
| REP-003 | Pendiente | Pendiente | Pendiente | Pendiente | Por evaluar |
| REP-004 | Pendiente | Pendiente | Pendiente | Pendiente | Por evaluar |
| REP-005 | Pendiente | Pendiente | Pendiente | Pendiente | Por evaluar |

### REP-001 — FastAPI

- Repositorio: https://github.com/fastapi/fastapi
- Lenguaje: Python
- Commit evaluado: f5c6e9b4f9cadc1bf0f9a1fd672e621206b63007
- Documentación: docs/en/docs/tutorial/path-params-numeric-validations.md
- Código de ejemplo: tests/main.py
- Pruebas funcionales: tests/test_path.py
- Requisito candidato: FASTAPI-REQ-001
- Resultado inicial: 2 pruebas aprobadas, 0 fallidas.
- Estado: Seleccionado provisionalmente.

### REP-002 — Flask

- Repositorio: https://github.com/pallets/flask
- Lenguaje: Python
- Commit evaluado: d086db856be187255b8ec61ef409357393020f32
- Documentación: docs/errorhandling.rst
- Código de prueba: tests/test_user_error_handler.py
- Prueba ejecutada: test_error_handler_http_subclass
- Requisito candidato: FLASK-REQ-001
- Resultado inicial: 1 prueba aprobada, 0 fallidas.
- Estado: Seleccionado provisionalmente.

## 5. Construcción del ground truth

Para cada requisito funcional se registrarán:

- Identificador y descripción del requisito.
- Repositorio y commit analizado.
- Archivo, función o fragmento relacionado.
- Etiqueta de relevancia verificada manualmente.
- Evidencia que justifica la etiqueta.
- Estado de cumplimiento funcional, cuando pueda verificarse.

La relevancia semántica y el cumplimiento funcional se evaluarán por separado.

## 6. Protocolo de evaluación

1. Seleccionar repositorios y fijar sus commits.
2. Extraer requisitos de documentación existente.
3. Obtener fragmentos de código mediante un procedimiento automático.
4. Etiquetar correspondencias con evidencias.
5. Ejecutar SBERT para recuperar los fragmentos más relevantes.
6. Comparar los resultados con el ground truth.
7. Calcular Recall@1, Recall@5 y MRR.
8. Registrar tiempos, errores y limitaciones.

## 7. Prevención de sesgos

- No seleccionar manualmente un único candidato correcto para cada requisito.
- No redactar requisitos copiando directamente el código.
- No modificar las etiquetas después de observar las predicciones de SBERT.
- Conservar casos negativos y difíciles.
- Separar los datos utilizados para ajustar el método de los datos de evaluación final.

## 8. Resultados

Pendiente de ejecutar los experimentos.
