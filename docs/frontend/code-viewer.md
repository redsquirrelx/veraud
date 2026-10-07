# Frontend Contract ΓÇö CodeViewer

Dumb, reusable read-only viewer for a source file. It renders line
numbers, per-language syntax highlighting, a file info bar and optional
agent marks with matching explanations. No fetching, no persistence, no
backend calls: the caller owns the code string and passes it in.

Source of truth: `frontend/src/shared/ui-kit/CodeViewer.tsx`
(render), `codeViewer.ts` (pure logic + types), `CodeViewer.css`
(styling contract), `CodeExplanations.tsx` (explanation list below the
viewer). Playground: `/test/file-viewer`.

## Import

```tsx
import { CodeViewer, CodeExplanations, type CodeViewerMark, type CodeExplanation } from "../../shared/ui-kit/index.ts"
```

## Props

| Prop | Type | Default | Meaning |
|---|---|---|---|
| `code` | `string` | required | Full file content. A single trailing newline is a terminator, not an extra blank line. |
| `language` | `string` | `""` | File extension without the dot: `ts`, `js`, `py`, `json`, `sh`. Anything else renders as plain text. |
| `highlight` | `boolean` | `false` | Enables `highlight.js` grammars (typescript, javascript, python, json, bash). |
| `marks` | `CodeViewerMark[]` | `[]` | Agent findings: `{ id: string, from: number, to: number, tone: CodeMarkTone, note?: string }`. Lines are 1-based and the range is inclusive. |
| `emptyText` | `string` | `"No content to show"` | Centered placeholder when `code` is empty. |

`CodeMarkTone` is `danger` \| `warning` \| `info`.

## Example

```tsx
<CodeViewer
  code={source}
  language="ts"
  highlight
  marks={[
    { id: "A", from: 8, to: 9, tone: "danger", note: "unvalidated amount reaches settle" },
    { id: "C", from: 1, to: 5, tone: "info" },
  ]}
/>
<CodeExplanations
  items={[
    { id: "A", tone: "danger", title: "Unvalidated amount", body: "Lines 8 to 9 throw a generic error." },
  ]}
/>
```

## Behaviour

- **File bar**: always visible, even for empty files. Size in `B`/`KB`
  measured from the UTF-8 encoded string, total line count (singular
  and plural handled), syntax label (`TypeScript`, `Python`, ΓÇª or
  `Plain text`), fixed `UTF-8` encoding and a right-aligned `Read-only`
  label with a lock icon. One row, one icon per item.
- **Lines**: 1-based numbers, blank lines preserved, horizontal scroll
  for long lines. The bar stays fixed: only `.ui-code-body` scrolls.
- **Highlighting**: per line, so a token spanning several lines (block
  comment, multiline string) is approximated, not tracked. Unknown
  languages fall back to plain text. `highlight.js` escapes its output,
  so `dangerouslySetInnerHTML` never receives raw code.
- **Marks**: one entry paints N lines, which is what makes ranges
  cheaper than one mark per line. Invalid ranges (`from < 1`,
  `to < from`, non-integers) are dropped; on overlap the first mark
  wins so output is deterministic. The `id` chip renders only on the
  first line of each range; `note`, when present, becomes the row
  `title` tooltip.
- **Explanations**: `CodeExplanations` takes `{ id, tone, title, body }`
  items and renders one box per item with the same chip and the same
  colour as its mark, so `A` in the code is `A` below. It renders
  nothing when the list is empty. Matching marks to boxes is the
  caller's job: the components share the `id` convention, nothing more.

## Internal state

None. `CodeViewer` derives everything with `useMemo` (`grammar`,
mark index) and memoizes each row, so a 500-line file only
re-highlights the lines whose text or grammar changed. `key={index}`
is safe because lines never reorder, insert or delete.

Above 500 lines the rows render progressively in chunks of 400 per
macrotask, with a percentage pill overlaid at the bottom, so opening a
long file never blocks the main thread. The first paint is already
chunked through a render-phase reset (not an effect), otherwise the
full parse would block before the pill appears. `key={index}` stays
stable because chunks only append.

## Styling contract

Classes the component relies on: `ui-code-viewer`, `ui-code-bar`,
`ui-code-meta`, `ui-code-readonly`, `ui-code-body`, `ui-code-line` plus
`ui-code-line-{danger,warning,info}`, `ui-code-number`, `ui-code-text`,
`ui-code-ref` plus `ui-code-ref-{tone}`, `ui-code-empty`, and for the
explanation list `ui-code-explanations`, `ui-code-explanation-{tone}`,
`ui-code-explanation-body`. Marked rows win over hover by rule order.
The viewer fills its column (`height: 100%`, floor `320px`, cap
`480px`) with its own scroll, so it lines up with the tree column
instead of growing with short files.

## Accessibility

`aria-label="File content"` on the block, `aria-hidden` line numbers,
`role="status"` with `aria-label="File info"` on the bar. Colour is
never the only signal: every mark also carries its `id` chip.

## Pure helpers

`codeViewer.ts` holds the logic with no JSX: `splitLines`,
`formatSize`, `resolveGrammar`, `languageLabel`, `highlightLine`,
`buildMarkIndex` and `rowClassName`, plus the `ALL` behaviour of an
empty language. Types: `CodeViewerMark`, `CodeExplanation`,
`CodeMarkTone`, `LineMark`. All of them are re-exported from
`shared/ui-kit/index.ts`.

Out of scope: fetching, editing, multi-file views, per-line selection
and real parsers (highlighting is regex-grade per line, by design).
