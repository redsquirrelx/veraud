# Task menu

`Dock` filters tasks from `useTasks` and renders `TaskMenu`. Initial active tasks
come from `GET /api/tasks/active`; later updates arrive through `task.updated`.
Both include `command` (string or null), recorded by the backend runner from
the same executable and arguments used for execution.

Each task header toggles an independent command detail below the row. Multiple
tasks can remain open; expansion is keyed by task ID and survives status changes
and toggling the whole menu. Enter and Space activate the header button, which
exposes `aria-expanded` and `aria-controls`.

The detail uses selectable monospace text and horizontal scrolling for long
commands. Tasks without a recorded command display "Command unavailable".
The command is a readable argument representation, not a shell script.
Expansion transitions respect `prefers-reduced-motion`.
