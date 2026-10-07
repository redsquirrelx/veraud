# Frontend Contract ΓÇö SplitView

Dumb, reusable two-pane layout with a draggable vertical divider. It
only splits width: the caller owns whatever lives in each pane.

Source of truth: `frontend/src/shared/ui-kit/SplitView.tsx`,
`SplitView.css`.

## Import

```tsx
import { SplitView } from "../../shared/ui-kit/index.ts"
```

## Props

| Prop | Type | Default | Meaning |
|---|---|---|---|
| `left` | `ReactNode` | required | Content of the left pane. |
| `right` | `ReactNode` | required | Content of the right pane, fills the remainder. |
| `initialRatio` | `number` | `0.5` | Left pane share of the width on first render, `0` to `1`. Clamped to the minimums. |
| `minRatio` | `number` | `0.2` | Neither pane goes below this share. |
| `label` | `string` | `"Resize panes"` | Accessible name of the divider. |

## Behaviour

- The divider is a `role="separator"` (`aria-orientation="vertical"`)
  with `aria-valuenow/min/max` in percent, focusable per default tab
  order. Drag with the pointer (primary button only, capture kept
  while dragging) or keyboard: arrows move 5 points, `Home`/`End` jump
  to the edges. Anything else is ignored.
- Panes never collapse: both keep at least `minRatio`, and moves
  without an active drag are ignored.
- No persistence: remounting resets to `initialRatio`.

## Used by the project detail

The Files section of `/projects/:id` renders a single `Card` with
`SplitView`: `CodeViewer` on the left, `DirectoryTree` on the right.
Each pane keeps its own loading, error and empty states, so one side
failing never takes the other down.

## Styling contract

`ui-split` (flex row), `ui-split-pane` (fixed share, left) and
`ui-split-pane-right` (fills the rest), `ui-split-handle` (10px wide,
`col-resize`, accent glow on hover/focus). Both panes need
`min-width: 0` from these classes or long content pushes the divider.

Out of scope: horizontal splits, persisted ratios, more than two panes.
