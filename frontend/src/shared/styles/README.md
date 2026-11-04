# Frontend visual styles

`tokens.css` is the single source for shared color, typography, spacing, radius, shadow, sizing, stacking and motion roles. Components consume these roles; page styles own page layout, not the visual skin of nested UI-kit controls.

Color text roles (`--color-text*`, `--status-*-text`, `--color-text-inverse`) are chosen for WCAG AA normal-text contrast on their documented surfaces. Functional borders/focus use `--color-border-control` and `--color-focus`; decorative dividers use the lighter `--color-border`. `--color-surface-recessed` is a fill, never a border. Disabled controls use their explicit disabled tokens rather than global opacity; WCAG exempts inactive controls from contrast thresholds.

## Ownership

- Global tokens are declared once in `tokens.css`, loaded before `index.css` from `main.tsx`. Future themes may override semantic roles on `html[data-theme]`; no theme UI or alternate palette is implemented yet. Portal content inherits from `html`.
- UI-kit components own their borders, backgrounds, typography, focus, hover and disabled visuals. Component-specific CSS is imported by the component itself, not incidentally through the barrel.
- Pages own composition (grid/flex, widths, responsive layout, positioning and margins) and use explicit component variants instead of overriding `.ui-*` appearance from ancestors.
- Picker/field shared rules live in `Field.css` and `ItemPicker.css`; popover skin lives in `MenuSurface.css`. Their React behavior remains in distinct components.
- `Card` and `Panel` preserve separate surface tones through explicit variants; Modal and Drawer keep distinct behavior and layout.
- `CodeReference.css` owns the shared solid marker chips for CodeViewer and CodeExplanations; their tone semantics stay aligned with danger/warning/info.

## Exceptions retained intentionally

- Breakpoints remain literal 480px, 600px and 760px because custom properties cannot be used in media-query thresholds.
- 4/6/8/12px radii, 28/32/36px controls, different focus offsets, local 0.65rem/9px values, and component-specific animation timings are retained where geometry or behavior differs.
- `--audit-accent` remains local to audit state/nesting and resolves through semantic status-accent tokens.
- Generated/semantic visuals (syntax theme, code evidence, Mermaid, progress, dynamic tree indentation and split ratio) are not recast as generic surfaces or static tokens.
- Diagram legend colors are named `--diagram-*` protocol tokens and intentionally keep their original values so existing report semantics remain truthful; they are not app-theme colors.
- `contrast.test.ts` statically resolves the documented opaque tokens and checks AA text / 3:1 graphical pairs. It cannot evaluate alpha compositing, opacity, SVG/highlight.js output or computed browser surfaces.

## Customization

To change the default brand, edit `--color-brand`, `--color-brand-hover` and `--color-brand-active`. To customize canvas/surfaces, edit `--color-canvas`, `--color-surface`, `--color-surface-tint`, `--color-surface-hover`, `--color-surface-recessed` and `--color-surface-active`. Change text and functional borders via `--color-text*` and `--color-border-control`, then run the contrast test; do not lighten muted text or controls borders without recalculating all documented pairs. Status roles are separate so their contrast can be checked independently. To change typography, edit `--font-sans` / `--font-mono`; shared type sizes consume `--font-size-*`. Control corner shape is `--radius-control`; card shape is `--radius-surface`.

The global token source intentionally does not mean every one-off dimension has a token. Do not add tokens for isolated declarations or rewrite dynamic values (Spinner size, tree depth, SplitView ratio, WAAPI timing) as constants.

Diagram-legend colors (`--diagram-*`) are fixed protocol colors documenting received report semantics, not app theme accents. Third-party highlight.js CSS and generated/received SVG cannot be guaranteed accessible by app tokens; audit rendered foreground/background combinations separately and do not rewrite data to make a ratio pass.
