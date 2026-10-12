# Inventario de endpoints HTTP del backend

Resultado del paso 1 del plan de integraci├│n de Swagger/OpenAPI.
Este documento conserva el diagn├│stico inicial. Para el estado actual de la
integraci├│n, consultar [el portal OpenAPI](openapi.md).
Revisi├│n: 11 de octubre de 2026. Fuente principal: controladores y servicios registrados en `backend/src/app.ts` (`buildApp`), contrastados con las pruebas y los contratos Markdown existentes.

## Resumen

| Grupo propuesto | Operaciones HTTP expl├¡citas |
| --- | ---: |
| Projects | 6 |
| Project Git | 6 |
| AI Providers | 8 |
| Tasks | 1 |
| Agent Executions | 5 |
| Status | 1 |
| **Total** | **27** |

Tambi├⌐n se registra `GET /ws` como WebSocket. No se cuenta como operaci├│n HTTP de negocio para OpenAPI. Los `HEAD` derivados de `GET` por Fastify y las respuestas `OPTIONS` de CORS tampoco se cuentan como operaciones independientes.

- 23 operaciones tienen esquemas de entrada parciales; 4 no tienen `schema`.
- Ninguna de las 27 define `schema.response`, `tags`, `summary` o `description` para OpenAPI.
- Ninguna define par├ímetros de consulta mediante `querystring`.
- No hay esquemas compartidos registrados con `app.addSchema()`.
- Los esquemas actuales son de validaci├│n; algunas restricciones y valores predeterminados se aplican en los servicios.
- Swagger y sus rutas `/docs` y `/docs/json` todav├¡a no est├ín registrados.

## Convenciones y formas de respuesta

Los campos listados describen las respuestas actuales, no nuevos contratos propuestos.

- **IDs de URL:** strings con patr├│n `^[0-9]+$`, convertidos con `Number()` en el controlador. No hay un m├¡nimo positivo en estos esquemas; no documentar `minimum: 1` como restricci├│n existente de los IDs de URL.
- **Fechas:** valores `Date` serializados como strings ISO en HTTP; documentar `format: date-time`.
- **Errores de dominio de proyectos/proveedores:** `{ message: string }`.
- **Errores de dominio de ejecuciones:** `{ error: string }`.
- **Errores de validaci├│n de Fastify:** respuesta propia del framework, con `statusCode`, `code`, `error` y `message`; distinta de ambos formatos de dominio. Los errores inesperados pueden producir una respuesta `500` del framework.
- **ProjectSummary:** `id`, `repositoryOwner`, `repositoryName`, `cloneProtocol` (`https`/`ssh`), `status`, `registeredAt`, `lastSyncedAt` nullable, `branch` nullable y `commitHash` nullable. `shallowClone` se persiste pero no se expone en estas respuestas.
- **RegisteredProject:** `id`, `repositoryOwner`, `repositoryName`, `status`. El registro devuelve el objeto creado con `status: QUEUED`, aunque espera a que finalice la clonaci├│n y el runner ya puede haber actualizado la fila a `READY`.
- **Execution:** `id`, `evaluationId` nullable, `agentType`, `status` (`Waiting`/`Running`/`Completed`/`Failed`), `result` nullable, `error` nullable, `inputTokens` nullable, `outputTokens` nullable, `createdAt`, `startedAt` nullable y `finishedAt` nullable. `result` es un string opaco, no un objeto JSON en la respuesta.
- **VersionAnalysis:** `id`, `branch` nullable, `commitHash` nullable, `analysisStatus`, `analyzedAt` nullable, `evaluationId` nullable, `execution` nullable y `derivedStatus`. `derivedStatus` procede del estado de ejecuci├│n o es `NeverAnalyzed`/`Pending`.
- **Model:** `id`, `name`, `inUse` boolean.
- **Credential:** `id`, `name`, `apiKeyPreview`, `inUse` boolean. Nunca devuelve la API key completa.
- **Provider:** `id`, `name`, `models: Model[]`, `credentials: Credential[]`.
- **Task:** `id`, `projectId`, `repositoryOwner`, `repositoryName`, `description` nullable, `command` nullable, `status`, `kind`, `exitCode` nullable. El estado de ├⌐xito existente se escribe `Succeded`; conservar esa graf├¡a en la documentaci├│n.

En las tablas, `400` incluye validaci├│n de Fastify cuando hay esquemas de entrada. Los c├│digos listados son los errores esperados de entrada/dominio; los fallos inesperados `500` se tratan por separado.

## Projects

Fuente: `backend/src/modules/project/project.controller.ts` y `project.service.ts`.

| M├⌐todo y ruta | Entrada actual | ├ëxito | Errores esperados | Esquema actual |
| --- | --- | --- | --- | --- |
| `GET /api/projects` | Sin body ni par├ímetros de consulta definidos | `200 ProjectSummary[]`; lista completa, ordenada por ID; puede estar vac├¡a | ΓÇö | Ninguno |
| `POST /api/projects` | Body: `repositoryUrl` string requerido; `shallowClone` boolean opcional | `201 RegisteredProject` | `400`, `409` duplicado, `422` acceso/clonaci├│n | Body |
| `POST /api/projects/:id/sync` | ID de proyecto; sin body requerido | `200 ProjectSummary` actualizado | `400`, `404`, `422` sincronizaci├│n | Params |
| `POST /api/projects/:id/file` | ID; body: `path` string requerido | `200 { path, content, size }`; `size` en bytes | `400`, `404`, `422` checkout/archivo | Params + body |
| `POST /api/projects/:id/analyze` | ID; body: `branch`, `commitHash` strings requeridos | `201 { versionId, evaluationId, execution: Execution }` | `400`, `404`, `422` checkout/agente/an├ílisis ya abierto | Params + body |
| `GET /api/projects/:id/versions` | ID de proyecto | `200 VersionAnalysis[]` | `400`, `404` | Params |

### Reglas que deben documentarse

- `repositoryUrl`: GitHub HTTPS o SSH (`git@github.com:owner/repo.git` o `ssh://git@github.com/owner/repo.git`). HTTPS consulta metadatos p├║blicos; SSH omite esa consulta y utiliza la configuraci├│n SSH del usuario del backend.
- `shallowClone` omitido equivale a `false` en el controlador/servicio. `true` a├▒ade `--depth 1`; el modo se conserva al reclonar. No existe `default` en el esquema actual.
- Registro y sincronizaci├│n esperan al comando Git. Una clonaci├│n fallida elimina la tarea y el proyecto reci├⌐n creados.
- Sincronizaci├│n: workspace vac├¡o ΓåÆ clone; HEAD adjunto ΓåÆ pull; HEAD separado ΓåÆ fetch. No convierte autom├íticamente un shallow clone en completo.
- Lectura de archivo: ruta recortada y barras invertidas normalizadas; m├íximo 1024 caracteres; rechaza segmentos vac├¡os, `.`/`..`, bytes nulos y `.git` como primer segmento. Archivo m├íximo de 512 KiB; rechaza directorios, archivos ausentes y contenido con bytes nulos. No crea una tarea.
- `analyze` valida branch/hash con las reglas Git indicadas abajo, reutiliza o crea la versi├│n, la selecciona, crea una evaluaci├│n y abre una ejecuci├│n en segundo plano. No hace checkout del commit como parte de este m├⌐todo.
- El mismo commit con una ejecuci├│n abierta devuelve `422`; otra versi├│n puede analizarse simult├íneamente.

## Project Git

Fuente: el mismo controlador/servicio de proyectos y `backend/src/infrastructure/task-runner/git.executor.ts`.

| M├⌐todo y ruta | Entrada actual | ├ëxito `200` | Errores esperados | Esquema actual |
| --- | --- | --- | --- | --- |
| `POST /api/projects/:id/git/branches` | ID; no exige body | `{ branches: string[], currentBranch: string\|null, detachedHash: string\|null, taskId }` | `400`, `404`, `422` | Params |
| `POST /api/projects/:id/git/tree` | ID; no exige body | `{ files: string[], taskId }` | `400`, `404`, `422` | Params |
| `POST /api/projects/:id/git/rev-parse` | ID; body: `branch` requerido | `{ branch, commitHash, taskId }` | `400`, `404`, `422` | Params + body |
| `POST /api/projects/:id/git/log` | ID; body: `branch` requerido, `limit`/`offset` integers opcionales | `{ branch, commits: [{ commitHash, subject }], limit, offset, taskId }` | `400`, `404`, `422` | Params + body |
| `POST /api/projects/:id/git/checkout` | ID; body: `commitHash` requerido | `{ commitHash, taskId }` | `400`, `404`, `422` | Params + body |
| `POST /api/projects/:id/git/checkout-branch` | ID; body: `branch` requerido | `{ branch, taskId }` | `400`, `404`, `422` | Params + body |

### Validaci├│n y comportamiento en servicios

- Branch: se recorta; 1ΓÇô255 caracteres, letras/n├║meros/punto/guion bajo/barra/guion. Rechaza `..`, `--`, prefijos `-`, `/`, `.`, y caracteres o secuencias Git especiales. El esquema del body solo indica string.
- Hash: 7ΓÇô40 caracteres hexadecimales, sin distinguir may├║sculas; se devuelve en min├║sculas. El esquema solo indica string. `rev-parse` exige una salida de 40 caracteres.
- Log: `limit` por defecto 30, rango 1ΓÇô100; `offset` por defecto 0, m├¡nimo 0. Rangos/defaults se aplican en el servicio, no en el esquema.
- Todas estas operaciones esperan a su tarea Git y devuelven `taskId`; las tareas fallidas se conservan. Checkout es forzado. Las operaciones de este grupo no actualizan el estado del proyecto.
- Branches incluye ramas locales y remotas, sin duplicados; un shallow clone solo muestra las referencias disponibles localmente. Tree enumera archivos de `HEAD`. Checkout de hash separa HEAD; checkout de branch lo adjunta.

## AI Providers

Fuentes: `backend/src/modules/ai-provider/ai-provider.controller.ts`, `ai-provider.service.ts` y `ai-provider.repository.ts`.

| M├⌐todo y ruta | Entrada actual | ├ëxito | Errores esperados | Esquema actual |
| --- | --- | --- | --- | --- |
| `GET /api/ai-providers` | Sin body | `200 Provider[]` | ΓÇö | Ninguno |
| `GET /api/ai-providers/:id` | ID de proveedor | `200 Provider` | `400`, `404` | Params |
| `POST /api/ai-providers/:id/models` | ID; body: `name` string requerido | `201 Model`, `inUse: false` | `400`, `404`, `409` | Params + body |
| `PATCH /api/ai-providers/:id/models/:nestedId` | IDs; body: `name` string requerido | `200 Model` | `400`, `404`, `409` | Params + body |
| `DELETE /api/ai-providers/:id/models/:nestedId` | IDs | `204` sin contenido | `400`, `404`, `409` | Params |
| `POST /api/ai-providers/:id/credentials` | ID; body: `name`, `apiKey` strings requeridos | `201 Credential`, `inUse: false` | `400`, `404`, `409` | Params + body |
| `PATCH /api/ai-providers/:id/credentials/:nestedId` | IDs; body: `name` requerido, `apiKey` opcional | `200 Credential` | `400`, `404`, `409` | Params + body |
| `DELETE /api/ai-providers/:id/credentials/:nestedId` | IDs | `204` sin contenido | `400`, `404`, `409` | Params |

### Reglas que deben documentarse

- Proveedores predefinidos: OpenAI, Anthropic y Google; no hay endpoints de creaci├│n/edici├│n/eliminaci├│n de proveedores.
- Nombres de modelo: se recortan, 1ΓÇô128 caracteres, empiezan por letra/n├║mero, permiten letras/n├║meros y `._/:-`, rechazan `..`.
- Nombres de credencial: se recortan, 1ΓÇô100 caracteres, empiezan por letra/n├║mero, permiten letras/n├║meros/espacios/guion bajo/guion.
- API key: se recorta, 1ΓÇô2000 caracteres, sin espacios internos. En PATCH, omitir `apiKey` conserva la existente; enviar un string vac├¡o es inv├ílido y devuelve `400`. El frontend omite el campo cuando su input queda vac├¡o.
- Nombres ├║nicos dentro del proveedor. PATCH permite conservar el mismo nombre y editar recursos en uso; DELETE de un recurso en uso devuelve `409`. IDs de recursos ajenos al proveedor devuelven `404`.
- `apiKeyPreview` es `****` m├ís los ├║ltimos cuatro caracteres, o solo `****` para claves de cuatro caracteres o menos. `inUse` indica referencias desde configuraciones de agentes.

## Tasks

Fuentes: `backend/src/modules/task/task.controller.ts`, `task.repository.ts` y `backend/src/infrastructure/task-runner/task.runner.ts`.

| M├⌐todo y ruta | Entrada actual | ├ëxito | Errores esperados | Esquema actual |
| --- | --- | --- | --- | --- |
| `GET /api/tasks/active` | Sin body | `200 Task[]` | ΓÇö | Ninguno |

- Solo filas `Queued`/`Running`, ordenadas por ID; una lista vac├¡a es v├ílida.
- `command` contiene la representaci├│n legible del ejecutable y argumentos, o null en tareas antiguas. No es un script de shell.
- La lista HTTP incluye owner/name; los eventos `task.updated` no incluyen esos dos campos. No reutilizar autom├íticamente un ├║nico esquema para ambos transportes.

## Agent Executions

Fuentes: `backend/src/modules/agent-execution/agent-execution.controller.ts`, `agent-execution.service.ts`, `agent-execution.repository.ts` y `backend/src/infrastructure/agent-target/direct-input.guard.ts`.

| M├⌐todo y ruta | Entrada actual | ├ëxito | Errores esperados | Esquema actual |
| --- | --- | --- | --- | --- |
| `POST /api/agent-executions` | Body: `agentType` string no vac├¡o y `evaluationId` integer ΓëÑ 1, requeridos | `201 Execution` inicial `Waiting` | `400`, `422` target inexistente | Body |
| `POST /api/agent-executions/direct` | Body: `agentType` string no vac├¡o e `input` objeto con ΓëÑ 1 propiedad, requeridos | `201 Execution`, `evaluationId: null` | `400`, `422` agente/input inv├ílido | Body |
| `GET /api/agent-executions/:id` | ID de ejecuci├│n | `200 Execution` | `400`, `404` | Params |
| `POST /api/agent-executions/:id/running` | ID; sin body requerido | `200 Execution` | `400`, `404` | Params |
| `POST /api/agent-executions/:id/completion` | ID; body: `status` requerido; `result`, `error`, `inputTokens`, `outputTokens` opcionales y nullable | `200 Execution` | `400`, `404`, `422` | Params + body |

### Reglas que deben documentarse

- Apertura devuelve inmediatamente y despacha en segundo plano; fallos posteriores de comunicaci├│n o checkout se reflejan en la ejecuci├│n, no en un nuevo c├│digo HTTP de la petici├│n inicial.
- Direct no crea evaluaci├│n ni versi├│n. Si existe `root_path`, debe resolver dentro del workspace; una ruta fuera devuelve `422` antes de crear la ejecuci├│n. Un checkout ausente falla la ejecuci├│n en segundo plano. Otros campos se pasan como input del agente.
- Completion solo permite `Completed`/`Failed`. `result`/`error`: string o null; tokens: integer ΓëÑ 0 o null. Campos omitidos se convierten en null.
- Para una ejecuci├│n abierta, `Failed` exige un `error` truthy (el servicio no recorta ni rechaza espacios en ese campo). Un callback de una ejecuci├│n ya terminada devuelve la fila sin sobrescribirla.
- Los callbacks de running/completion son endpoints del backend aunque normalmente los invoque el agent-server; forman parte del inventario.

## Status

Fuente: `backend/src/app.ts` (`checkAgentServer`).

| M├⌐todo y ruta | Entrada actual | ├ëxito | Errores esperados | Esquema actual |
| --- | --- | --- | --- | --- |
| `GET /status` | Sin body | `200 { status: "ok", service: "backend", agentServer: "online"\|"offline"\|"unknown" }` | ΓÇö | Ninguno |

Sin URL configurada, el estado es `unknown`. Si la consulta a `/api/status` del agent-server falla, excede el timeout de 2000 ms o no devuelve un status exitoso, es `offline`; la respuesta HTTP del backend sigue siendo `200`.

## Contraste con documentaci├│n y pruebas existentes

La revisi├│n de pruebas es est├ítica en este paso; no se ejecut├│ una nueva suite ni se modific├│ el comportamiento.

| ├ürea | Documentaci├│n revisada (`docs/backend/`) | Pruebas revisadas (`backend/src/`) | Hallazgos |
| --- | --- | --- | --- |
| Registro | `project-registration.md` | `projects.integration.test.ts`, `modules/project/project.controller.test.ts`, `modules/project/project.service.test.ts` | Incluye shallow clone, HTTPS/SSH, duplicados y rollback. `QUEUED` en la respuesta inicial no representa necesariamente el estado persistido tras clonar. |
| Listado/sync | `project-listing.md`, `project-sync.md` | `tests/project-listing.*.test.ts`, `tests/project-sync.integration.test.ts`, `modules/project/project.service.test.ts` | Campos del listado coinciden. La frase de sync ┬½keeps the current branch and commit┬╗ es imprecisa: pull conserva la rama pero puede avanzar el commit; fetch con HEAD separado no lo mueve. |
| Git/archivos | `project-branches.md`, `project-files.md` | `tests/project-git.integration.test.ts`, `modules/project/project-git.service.test.ts`, `infrastructure/task-runner/task-git.test.ts` | Docs describen body vac├¡o para branches/tree, pero los controladores no lo exigen. La menci├│n a stderr en `logTrail` describe la tarea, no el body HTTP del error. La referencia a colapsar separadores duplicados en file contradice la validaci├│n: segmentos vac├¡os se rechazan. |
| Proveedores | `ai-providers.md` | `modules/ai-provider/ai-providers.integration.test.ts`, `modules/ai-provider/ai-provider.service.test.ts` | CRUD y errores coinciden. Explicitar en Swagger que PATCH con API key vac├¡a no equivale a omitirla. |
| Tareas | `project-registration.md` | `modules/task/task.controller.test.ts`, `modules/task/task.service.test.ts`, `infrastructure/task-runner/task.runner.test.ts`, `projects.integration.test.ts` | `command` aparece en un p├írrafo posterior, pero no en la lista inicial de campos; incluirlo en el contrato unificado de HTTP. |
| Ejecuciones/an├ílisis | `agent-execution.md` | `tests/agent-execution.integration.test.ts`, `tests/project-analyze.integration.test.ts` | Markdown no incluye una secci├│n para `/direct` ni contratos HTTP completos de `/analyze` y `/versions`. Errores de ejecuciones usan `{ error }`, no `{ message }`. |
| Status | Sin contrato espec├¡fico en esos documentos | `tests/status.test.ts` | Incluir `/status`, sin prefijo `/api`, con los tres estados del agent-server. |

## Lista de contratos pendientes para los pasos siguientes

1. **Metadatos de las 27 operaciones:** tags, summary, description y ejemplos.
2. **Respuesta exitosa de las 27 operaciones:** definir todos los campos, arrays, nullable y fechas; representar los dos DELETE como `204` sin body.
3. **Errores:** conservar ambos formatos de dominio y diferenciar la validaci├│n de Fastify; registrar los c├│digos por endpoint indicados en las tablas.
4. **Cuatro rutas sin schema:** listado de proyectos, listado de proveedores, tareas activas y status necesitan sus contratos de respuesta/metadatos.
5. **Restricciones de servicio:** documentar branch/hash/path, l├¡mites del log, nombres y API keys, sin cambiar accidentalmente normalizaci├│n o validaci├│n al trasladar restricciones al schema.
6. **Defaults y comportamiento:** shallow clone omitido ΓåÆ false, log 30/0, apertura as├¡ncrona y callbacks idempotentes; distinguir respuestas iniciales de estados posteriores.
7. **Esquemas compartidos candidatos:** ProjectSummary, RegisteredProject, Execution, VersionAnalysis, Provider, Model, Credential, Task y los distintos errores. No usar filas Prisma completas como contratos p├║blicos.
8. **Conciliar Markdown:** actualizar las diferencias se├▒aladas al introducir la documentaci├│n central. WebSocket mantiene sus propios contratos fuera del inventario HTTP.

## Criterio de finalizaci├│n del paso 1

Las 27 operaciones expl├¡citas registradas en `buildApp` est├ín enumeradas, con entradas, respuestas, errores, estado de sus esquemas y fuentes de contraste. Este documento constituye la referencia para medir la cobertura cuando se integre OpenAPI.
