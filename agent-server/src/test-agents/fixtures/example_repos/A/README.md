# Suite de parches para FindingResolutionAgent — fixture_A

Esta batería contiene **34 patches independientes** y un control sin cambios.
Fue construida con el repositorio original enviado por el usuario; la estructura de archivos de cada patch usa rutas relativas a la raíz de `fixture_A`.

## Uso (PowerShell)

Cada patch **se aplica sobre un checkout limpio**. Ejemplo:

```powershell
cd ruta\a\fixture_A
git status --short
git apply --check ruta\a\finding_resolution_patch_suite\patches\001-fix-domain-di.patch
git apply ruta\a\finding_resolution_patch_suite\patches\001-fix-domain-di.patch
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
python -m shoplab.app
```

Recomendado: crear una **copia temporal del repositorio original por escenario**. No apilar patches ni aplicar sobre un árbol con cambios sin confirmar.
En Git, para revertir cambios exclusivamente del escenario (si no tienes cambios propios): `git reset --hard HEAD` y `git clean -fd` (ambos eliminan cambios no guardados). Es preferible eliminar la copia temporal.

### Resultado esperado

El archivo `expected-results.json` contiene un oráculo de 3 decisiones (`finding_id` → `resolved` / `persists`) por escenario, categorías, razones, paths modificados, hash del patch y verificaciones realizadas.
**Orden de columnas:** dominio, acceso privado desde billing, encapsulación del inventario.

| Patch | Tipo | Dominio / Billing / Encapsulación | Escenario |
|---|---|---|---|
| `001-fix-domain-di` | fix | resolved / persists / persists | Domain dependency injection |
| `002-fix-inventory-api` | fix | persists / resolved / resolved | Billing uses inventory public API |
| `003-fix-all` | fix | resolved / resolved / resolved | Fix both architectural violations |
| `004-fix-domain-relocate-out-of-domain` | fix | resolved / persists / persists | Move notification to application boundary |
| `005-fix-billing-new-public-operation` | fix | persists / resolved / resolved | Alternative public inventory operation |
| `006-fix-domain-pure-message` | fix | resolved / persists / persists | Extract pure domain message building |
| `007-fix-billing-relocate-public` | fix | persists / resolved / resolved | Relocate billing implementation and remove private access |
| `008-fix-domain-remove-feature` | fix | resolved / persists / persists | Legitimate removal of special confirmation feature |
| `101-claim-fixed-in-comments` | adversarial | persists / persists / persists | Misleading comments claim resolution |
| `102-refactor-formatting-only` | superficial | persists / persists / persists | Source formatting, docstrings and line movements |
| `103-import-aliases` | obfuscation | persists / persists / persists | Alias direct imports without changing dependencies |
| `104-local-imports` | obfuscation | persists / persists / persists | Move imports inside functions |
| `105-dynamic-imports` | obfuscation | persists / persists / persists | Use importlib to defer both violations |
| `106-domain-delegates-bad-helper` | relocation | persists / persists / persists | Move concrete dependency into a different domain module |
| `107-domain-renamed-module` | relocation | persists / persists / persists | Rename domain violation module |
| `108-billing-bad-helper` | relocation | persists / persists / persists | Move backing-store access to another billing module |
| `109-billing-renamed-module` | relocation | persists / persists / persists | Rename billing implementation while retaining violation |
| `110-internal-storage-renamed` | relocation | persists / persists / persists | Rename private inventory store module |
| `111-direct-stock-import` | obfuscation | persists / persists / persists | Replace private module import with direct STOCK import |
| `112-reflective-stock-access` | obfuscation | persists / persists / persists | Access private state through getattr |
| `113-reexport-private-store` | deceptive-api | persists / persists / persists | Re-export private store under public-looking alias |
| `114-billing-local-wrapper` | deceptive-api | persists / persists / persists | Add billing-local facade over the private store |
| `115-partial-billing-fallback` | partial | persists / persists / persists | Use public API for most SKUs, private state on PEN |
| `116-partial-domain-injected-default` | partial | persists / persists / persists | Add notifier injection but keep concrete default |
| `117-domain-through-application-factory` | transitive | persists / persists / persists | Route domain->application->infrastructure |
| `118-relative-imports` | obfuscation | persists / persists / persists | Use relative imports to conceal package names |
| `119-tests-and-readme-only` | superficial | persists / persists / persists | Change tests and documentation without touching violations |
| `120-public-mutable-stock-leak` | deceptive-api | persists / persists / persists | Publish mutable private stock dictionary as an API |
| `121-domain-named-wrapper-with-direct-infra` | partial | persists / persists / persists | Introduce interface but bridge still instantiates implementation |
| `122-private-access-via-importlib-dunder` | obfuscation | persists / persists / persists | Import private inventory state with __import__ |
| `201-fix-domain-but-alias-billing` | mixed | resolved / persists / persists | Fix domain, obfuscate billing |
| `202-fix-billing-but-dynamic-domain` | mixed | persists / resolved / resolved | Fix billing, retain dynamic domain dependency |
| `203-apparent-fix-all-billing-fallback` | mixed | resolved / persists / persists | Fix domain and billing main path, leave PEN fallback |
| `204-apparent-fix-all-domain-default` | mixed | persists / resolved / resolved | Fix billing and add optional domain injection |

## Qué significan las etiquetas

- **fix:** la violación original se elimina realmente.
- **superficial:** cambian textos, pruebas o presentación sin arreglar el problema.
- **obfuscation:** el acceso indebido persiste usando otra sintaxis o nombres.
- **relocation:** el código problemático se mueve de archivo o módulo sin eliminar la transgresión arquitectónica.
- **deceptive-api:** se ofrece una API aparentemente pública que expone los detalles internos; la encapsulación sigue vulnerada.
- **partial:** se agrega una solución parcial, manteniendo al menos una ruta alcanzable que viola el límite.
- **transitive:** se introduce una dependencia arquitectónica indirecta del dominio hacia infraestructura.
- **mixed:** se resuelve una violación, mientras que otra permanece.
- **adversarial:** los comentarios o la documentación afirman erróneamente que se corrigió el problema.

Los hallazgos `candidate:billing-inventory-store-access` y `candidate:inventory-encapsulation-bypass` tratan **la misma conducta de billing** desde perspectivas cercanas; por tanto cambian juntos en esta batería.

## Detalles metodológicos

1. Cada patch se generó contra el commit original del ZIP, desde cero.
2. Se verificó con `git apply --check` y `git apply` sobre una copia limpia independiente.
3. Se validó sintaxis Python mediante `ast.parse`.
4. Se ejecutaron **las 2 pruebas unitarias originales** y `python -m shoplab.app` para cada escenario. Estos smoke tests no garantizan que se corrigió la arquitectura, ni que todos los caminos de ejecución están cubiertos.
5. Los `expected` son **ground truth previsto por construcción**, NO resultados reales del LLM. Compara tus ejecuciones contra ellos y registra los desacuerdos para inspección manual.
6. Para resultados `inconclusive`, utiliza escenarios de **fallo de herramientas, tiempo, límites, evidencia inaccesible o esquema inválido** en el script/harness. Un patch sobre un repositorio plenamente legible, por sí solo, no suele justificar un `inconclusive` determinista.
7. **El patch `008-fix-domain-remove-feature` elimina deliberadamente la notificación especial**: resuelve la dependencia estructural, pero cambia funcionalidad. Úsalo para distinguir resolución arquitectónica de preservación funcional.
8. Algunas pruebas más difíciles (dependencia transitiva, movimiento o `importlib`) podrían producir falsos `resolved` si el agente se restringe a la ruta histórica. Eso es exactamente lo que se quiere medir.
9. Para medir reproducibilidad, ejecuta varios intentos por escenario, registra `snapshot_hash`, respuesta, IDs de evidencia, coste/tokens y variación entre corridas.

## Comando para aplicar un patch desde script Python

### Ejecución y comparación automática

Desde `agent-server/`:

```powershell
uv run python src/test-agents/run_finding_resolution_scenarios.py --scenario 003-fix-all --report report.json
```

Sin `--scenario` se ejecutan el control y los 34 patches, cada uno en una copia
temporal independiente. Usa el LLM configurado y puede generar costes.
El reporte conserva los metadatos del escenario, diagnósticos, trazas y consumo;
compara `FindingResolutionResult` por `finding_id` y `status`, sin exigir orden,
igualdad textual de `reason` ni igualdad de `evidence_ids`. Las razones no vacías
y las citas actuales del hallazgo se validan por separado. El mapa `expected`
original se conserva como proyección ID → estado del contrato final.

Usa `subprocess.run(['git','apply','--check',patch],cwd=repo_copia,check=True)` y después `subprocess.run(['git','apply',patch],cwd=repo_copia,check=True)`; construye **un nuevo snapshot** del repositorio modificado antes de ejecutar el agente.
