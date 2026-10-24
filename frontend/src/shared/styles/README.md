# Frontend visual styles

`tokens.css` is the single source for shared color, typography, spacing, radius, shadow, sizing, stacking and motion roles. Components consume these roles; page styles own page layout, not the visual skin of nested UI-kit controls.

## Ownership

- Global tokens are declared once in `tokens.css`, loaded before `index.css` from `main.tsx`. Future themes may override semantic roles on `html[data-theme]`; no theme UI or alternate palette is implemented yet. Portal content inherits from `html`.
- UI-kit components own their borders, backgrounds, typography, focus, hover and disabled visuals. Component-specific CSS is imported by the component itself, not incidentally through the barrel.
- Pages own composition (grid/flex, widths, responsive layout, positioning and margins) and use explicit component variants instead of overriding `.ui-*` appearance from ancestors.
- Picker/field shared rules live in `Field.css` and `ItemPicker.css`; popover skin lives in `MenuSurface.css`. Their React behavior remains in distinct components.
- `Card` and `Panel` preserve separate surface tones through explicit variants; Modal and Drawer keep distinct behavior and layout.

## Exceptions retained intentionally

- Breakpoints remain literal 480px, 600px and 760px because custom properties cannot be used in media-query thresholds.
- 4/6/8/12px radii, 28/32/36px controls, different focus offsets, local 0.65rem/9px values, and component-specific animation timings are retained where geometry or behavior differs.
- `--audit-accent` remains local to audit state/nesting and resolves through semantic status-accent tokens.
- Generated/semantic visuals (syntax theme, code evidence, Mermaid, progress, dynamic tree indentation and split ratio) are not recast as generic surfaces or static tokens.

## Customization

To change the default brand, edit `--color-brand` and, if needed, `--color-brand-hover`. To customize the base canvas/surfaces, edit `--color-canvas`, `--color-surface` and `--color-surface-tint`; text-on-brand is separate. To change typography, edit `--font-sans` / `--font-mono`; shared type sizes consume `--font-size-*`. Control corner shape is `--radius-control`; card shape is `--radius-surface`.

The global token source intentionally does not mean every one-off dimension has a token. Do not add tokens for isolated declarations or rewrite dynamic values (Spinner size, tree depth, SplitView ratio, WAAPI timing) as constants.
