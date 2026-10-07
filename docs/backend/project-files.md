# Backend Contract ΓÇö Project Files

`POST /api/projects/:id/file` reads one text file from the workspace
checkout so the UI can preview it next to the directory tree. It is a
plain filesystem read, not a git command: no task row is created and
nothing is broadcast.

Source of truth: `backend/src/modules/project/project.service.ts`
(`readFile`), `project.controller.ts`.

## `POST /api/projects/:id/file`

Request: `path` (string, required) ΓÇö workspace-relative file path with
forward slashes, resolved against the checked-out folder, so it always
follows the selected version.

```json
{ "path": "src/modules/engine.ts" }
```

Response `200`: `path` (normalized with duplicate separators and
backslashes collapsed), `content` (UTF-8 text) and `size` (bytes).

Validation: empty, absolute, `.`/`..`/empty segments, null bytes and
anything under `.git/` return `400` without touching the disk beyond
the check. The resolved path must stay inside the checkout, otherwise
`400`.

## Errors

| Code | Meaning |
|---|---|
| `400` | Non-numeric id, malformed body or path escaping the checkout |
| `404` | Unknown project |
| `422` | Missing checkout, or path is not a readable text file (missing, directory, larger than 512 KB, binary) |

Out of scope: listings (`POST /api/projects/:id/git/tree`), writes.
