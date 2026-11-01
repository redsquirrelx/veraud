# Lightweight audit history

`GET /api/projects/:id/audits?limit=5&offset=0` returns:

```text
{ items: [...summaries], total, hasRunning, limit, offset }
```

- `limit`: 1–100; defaults to 5 when only `offset` is supplied.
- `offset`: nonnegative integer; defaults to 0. Offsets beyond the history are
  clamped to the last page. Empty histories return offset 0.
- Order: creation date descending, then execution ID descending.
- `hasRunning` covers the entire project, including runs outside the page.
- Requests without pagination retain the legacy summary-array response.

The repository selects execution metadata and projects only the required JSON
fields in SQLite for the selected page. Full results, Blackboard data, Word
documents, invocation receipts, operating configuration and detailed errors are
not materialized in Node for this listing. SQLite still reads the stored JSON to
extract summary fields; no denormalized columns or database migrations are added.
Saved audit branch, commit and attributes take precedence over mutable version
metadata. Report and configuration availability remain part of the summary.

The frontend requests one page at a time, aborts obsolete requests and polls that
page while any project audit is active. Run IDs come from summaries, without
per-row detail requests. The agent catalog is loaded only for audit setup or an
explicit configuration reuse action. Reports and saved configuration remain
on-demand reads.
