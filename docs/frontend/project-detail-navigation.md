# Navegaci├│n del detalle del proyecto

## Distribuci├│n

- `AppLayout` mantiene Toasts, Dock y la consulta ├║nica de estado de servicios.
- `StandardLayout` muestra la cabecera global en Home, Settings y playgrounds.
- `ProjectLayout` aloja `/projects/:id` y transmite el estado por `Outlet`.
- `ProjectSidebar` re├║ne marca, enlaces Home/Settings, secciones del proyecto,
  documentaci├│n y servicios. La expansi├│n usa `sidebar.expanded` del storage
  de infrastructure.
- `ProjectHeader` es la barra superior sticky del detalle. Conserva identidad,
  versi├│n y acciones entre secciones: t├¡tulo y `On {branch} at {commit}` en la
  primera fila, con Sync y Analyze a la derecha (Analyze en el extremo), y
  selectores compactos debajo.
- El layout ocupa `100dvh`; solo `project-content` tiene scroll vertical. El
  lateral permanece fuera de ese panel y la cabecera es sticky dentro de ├⌐l.
- Overview contiene fechas, GitHub y resumen; Audits contiene ejecuci├│n y
  configuraci├│n capturada; Files contiene ├írbol y vista previa.

Hasta 760 px el lateral pasa a una barra superior con grupos que se ajustan en
varias filas. La preferencia de expansi├│n se conserva. Branch y Commit ocupan
filas completas; las acciones siguen junto al t├¡tulo. Los nombres largos se recortan
en el bot├│n del selector y se pueden leer completos en sus opciones.

API docs abre hacia la derecha en escritorio y debajo en pantallas peque├▒as.
Los contenedores de navegaci├│n no recortan los desplegables. Los controles
contra├¡dos tienen nombre accesible y tooltip. Las pesta├▒as Git/Analyzed admiten
flechas, Home y End; el selector admite flechas, Enter, Escape con restauraci├│n
de foco y cierre al abandonar el control con Tab.

La expansi├│n del lateral usa Web Animations: 250 ms para ancho/padding (altura
en la barra m├│vil) y 200 ms de entrada con opacidad y desplazamiento del contenido.
Al invertir la animaci├│n se parte del tama├▒o visible. Esta animaci├│n expl├¡cita
se mantiene activada conforme a la preferencia solicitada para este lateral.

## Evidencia de verificaci├│n

Verificaci├│n del 12 de octubre de 2026, sin automatizaci├│n de navegador:

| Flujo | Evidencia |
| --- | --- |
| Home ΓåÆ detalle ΓåÆ Settings ΓåÆ volver | `frontend/src/app/project-navigation.test.tsx`, rutas y p├íginas reales con HTTP simulado |
| URL directa y persistencia tras nuevo montaje | `project-navigation.test.tsx`, router en memoria creado de nuevo |
| API docs y lateral contra├¡do | `project-navigation.test.tsx` y `frontend/src/pages/project/ProjectSidebar.test.tsx` |
| Versiones Git/analizadas y checkout | `frontend/src/features/project-management/VersionSelector.test.tsx` y `frontend/src/pages/project/ProjectDetailPage.test.tsx` |
| Analyze/Sync, errores y carga | `ProjectDetailPage.test.tsx` y `project-navigation.test.tsx` |
| Overview/Audits/Files, vista previa y configuraci├│n | `ProjectDetailPage.test.tsx` |
| Teclado y foco de pesta├▒as/selectores/documentaci├│n | `frontend/src/shared/ui-kit/FilterTabs.test.tsx`, `ItemSelector.test.tsx` y `DropdownLinks.test.tsx` |
| Toasts, Dock y consulta com├║n | `frontend/src/app/layout.test.tsx` y suite de Dock/estado |

Comandos ejecutados desde `frontend/`:

```text
pnpm exec vitest run --maxWorkers=2  # 374 pruebas, 57 archivos, todas correctas
pnpm run build                     # TypeScript y build correctos
pnpm run lint                      # correcto
```

`git -c core.safecrlf=false diff --check` tambi├⌐n pas├│ desde la ra├¡z.

La revisi├│n manual de c├│digo cubri├│ anchos m├¡nimos, ajuste de filas, nombres
largos, posici├│n de desplegables, foco y etiquetas. No se realiz├│ una inspecci├│n
visual en un navegador ni una recarga HTTP real; el montaje directo se verific├│
con el router en memoria. Tampoco se ejecutaron an├ílisis con credenciales reales.

### Comprobaci├│n visual local

Para la revisi├│n visual, abrir un proyecto a 320, 760 y 1280 px, tanto expandido
como contra├¡do. Revisar los nombres largos, apertura de Branch/Commit/API docs,
foco con Tab y Escape, y ausencia de desbordamiento horizontal. Recargar una URL
`/projects/:id` y confirmar que se restaura la preferencia del lateral.
