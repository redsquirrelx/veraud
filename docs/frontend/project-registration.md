# Frontend Contract — Project Registration

Single main page: auditor pastes a GitHub URL, registers the project,
follows the clone in a docked task menu, gets toast feedback.

Source of truth: `frontend/src/features/project-management/`,
`shared/ui-kit/`, `infrastructure/http-client/`

## Pieces (only these)

- `app/`: layout + router (`/` home, `/test` playground).
- `features/project-management/`: `ProjectRegistrationForm` (presentational),
  `useRegisterProject` (owns url + `idle → loading → success | error`),
  `useTasks` (initial `GET /api/tasks/active` + live `/ws` merge),
  `TaskMenu` (docked list, spinner per running task, hides when empty).
- `shared/ui-kit/`: dumb `Button` (`loadingText="Espere"`, no spinner),
  `TextInput`, `Toast` (auto-dismiss, hover pause, expander).
- `infrastructure/http-client/`: throws typed `ApiError` (status + backend
  `message`) on non-2xx.

Out of scope: Code Explorer, Audit Management.

## Behavior

- Button disabled until a GitHub URL is present.
- On click: input clears at once, button cools down 2s (then it accepts
  the next URL while the first clone still runs; clones queue server-side).
- Task menu (bottom-right dock, toasts above it): finished tasks stay with
  their final status; collapsed shows the running task, expanded (chevron
  down) shows all oldest-first with scroll, each row with the task
  `description` (`cloning owner/repo`), spinner and right-aligned status.
  The menu slides up on appear (down on close), never closes alone
  (X to close, reopens on new tasks); "no queued tasks" only shows
  expanded when empty.
- `201`: success toast in the dock (clone confirmed), menu entry leaves.
- Error: toast backend `message`, re-enable, nothing stored.

## Backend API used

`POST /api/projects` with `repositoryUrl` (string).

```json
{ "repositoryUrl": "https://github.com/fintech-core/payment-gateway-v2" }
```

Response `201`: `id`, `repositoryOwner`, `repositoryName`, `status`.
Errors: `400` bad URL, `409` duplicate, `422` not accessible/clone failed.
Live: `GET /api/tasks/active` + WS `/ws` (`task.updated`).
Full spec: `docs/backend/project-registration.md`.
