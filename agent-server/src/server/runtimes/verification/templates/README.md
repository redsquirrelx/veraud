# Tallercito — Verification Suite (audit __AUDIT_ID__)

Suite de verificación **portable** generada a partir de los hallazgos de la
auditoría __AUDIT_ID__ (commit `__SOURCE_COMMIT__`).

## Qué es y qué no es

- Cada prueba demuestra, **en el alcance declarado en `manifest.json`**, si la
  condición observable denunciada por un hallazgo persiste en este repositorio.
- Un resultado `INCONCLUSIVE` **no** prueba que la condición haya desaparecido;
  solo "ninguna verificación denunció la condición" consta en este checkout.
- Los hallazgos originales conservan su `verification_status` (`unreviewed` /
  `inconclusive`); ejecutar esta suite no los revisa.

## Requisitos

- [`uv`](https://docs.astral.sh/uv/) en el PATH. Si no está disponible,
  ejecute manualmente: `uv run --project .tallercito python .tallercito/runner.py`
- Un checkout de este repositorio (recomendado en `__SOURCE_COMMIT__`).

## Ejecución

Windows:

```bat
.tallercito\run.bat
```

Linux / macOS:

```sh
./.tallercito/run.sh
```

## Filtrado por subcategoría

El manifiesto (`manifest.json`) etiqueta cada verificación con `group` (la
subcaracterística del hallazgo, p. ej. `testability` o `modularity`). Para
ejecutar solo un grupo, use `--only`; para ver los grupos presentes, use
`--list-groups`:

```sh
./.tallercito/run.sh --list-groups
./.tallercito/run.sh --only testability
```

Funciona invocada desde cualquier directorio: la raíz se calcula a partir de la
ubicación de `runner.py`, nunca de la carpeta actual.

## Códigos de salida

| Código | Significado |
|---|---|
| 0 | Ninguna violación observada en las verificaciones ejecutadas (puede incluir resultados `INCONCLUSIVE`) |
| 1 | Al menos una violación detectada (ver `results/report.json`) |
| 2 | Error de entorno/ejecución o ninguna verificación alcanzó un veredicto |

## Resultados

`results/report.json` (máquina) y `results/report.md` (humano): por cada
verificación, el hallazgo, la condición comprobada, el resultado y las
limitaciones declaradas. El runner **no** modifica código fuente.

## Advertencias

- Esta suite ejecuta código Python del repositorio (imports estáticos y, en el
  caso de las pruebas híbridas, ejecución real de módulos). Revísela antes de
  usarla en un entorno sensible.
- Los imports estáticos no cubren imports dinámicos (`importlib`); cada
  limitación concreta se lista en el manifiesto y en el reporte.
