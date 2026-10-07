# Frontend Contract — Toasts

Global, fire-and-forget notifications for async action outcomes. Pages
never render `Toast` directly for these: they call
`pushToast(kind, message)` from `useToasts()` and the `Dock` renders
every toast bottom-right, above the task menu. No fetching, no
persistence: the provider owns the list in memory and forgets it on
reload.

Source of truth: `frontend/src/app/toasts.tsx` (provider),
`use-toasts.ts` (context + hook), `dock.tsx` (render site),
`frontend/src/shared/ui-kit/Toast.tsx` (dumb box), `Toast.css`
(styling contract). Used by project registration, project
sync/version apply and the settings LLM admin.

## Import

```tsx
import { useToasts } from "../../app/use-toasts.ts"

const { pushToast } = useToasts()
pushToast("success", "Model o1 registered")
```

## API

| Member | Type | Meaning |
|---|---|---|
| `pushToast` | `(kind, message) => void` | Appends a toast. `kind` is `success` \| `error`. Messages are caller-owned English strings, usually the backend `ApiError` text on failure. |
| `dismissToast` | `(id) => void` | Removes one toast. The `Dock` wires it to each box; pages never call it. |
| `toasts` | `ToastItem[]` | Current boxes. The `Dock` is the only reader. |

`useToasts()` outside `ToastProvider` throws. `AppLayout`
(`app/layout.tsx`) wraps the whole app, so every page is covered;
tests render their own `ToastProvider`.

## Behaviour

- **Lifetime**: each box auto-closes after 5 seconds and pauses while
  hovered. The X closes immediately with a 200 ms exit animation.
  Long messages (over 120 chars) clamp to two lines with a
  Show more/less toggle.
- **Tone**: `success` renders `role="status"`, `error` renders
  `role="alert"`, so failures interrupt assistive tech and successes
  do not.
- **Placement**: the `Dock` is fixed bottom-right (`360px` wide) and
  stacks toasts above the live task menu, newest last.

## Usage rule

- Outcome of an async user action (register, sync, create, delete)
  goes global via `pushToast`, in both the success and the failure
  branch, with the backend message verbatim on failure.
- Contextual form errors stay inline next to the failing field (for
  example the settings modals keep their red line) and the modal
  stays open, so the toast is a record and the inline error is the
  fixer. The two may carry the same text by design.
- Never `pushToast` for live task progress: that belongs to the task
  menu and its visibility toggles.

Out of scope: queues with limits, persistence across reloads and
per-toast actions beyond closing.
