import { memo, useEffect, useMemo, useRef, useState } from "react"
import { CodeIcon, DatabaseIcon, ListIcon, LockIcon, TypeIcon } from "./icons.tsx"
import { Spinner } from "./Spinner.tsx"
import {
  buildMarkIndex,
  formatSize,
  highlightLine,
  languageLabel,
  resolveGrammar,
  rowClassName,
  splitLines,
  type CodeViewerMark,
  type LineMark,
} from "./codeViewer.ts"
import "./CodeViewer.css"
// Keep the theme import next to the component: it was lost once when the
// logic moved to codeViewer.ts, and nothing but the browser shows it.
import "highlight.js/styles/github.css"

interface CodeViewerProps {
  code: string
  language?: string
  highlight?: boolean
  marks?: CodeViewerMark[]
  emptyText?: string
}

interface CodeLineProps {
  line: string
  number: number
  grammar: string | null
  mark: LineMark | null
}

const PROGRESSIVE_THRESHOLD = 500
const PROGRESSIVE_CHUNK = 400

// Memoized: a 500-line file re-renders every row on each parent update,
// and each highlight call parses its line again.
const CodeLine = memo(function CodeLine({ line, number, grammar, mark }: CodeLineProps) {
  const highlighted = useMemo(() => highlightLine(line, grammar), [line, grammar])

  return (
    <span className={rowClassName(mark)} title={mark?.note ?? undefined}>
      <span className="ui-code-number" aria-hidden="true">{number}</span>
      {highlighted === null ? (
        <span className="ui-code-text">{line === "" ? " " : line}</span>
      ) : (
        <span className="ui-code-text" dangerouslySetInnerHTML={{ __html: highlighted }} />
      )}
      {mark !== null && mark.first && (
        <span className={`ui-code-ref ui-code-ref-${mark.tone}`}>{mark.id}</span>
      )}
    </span>
  )
})

function FileBar({ code, grammar }: { code: string, grammar: string | null }) {
  const bytes = new TextEncoder().encode(code).length
  const lines = splitLines(code).length

  return (
    <div className="ui-code-bar" role="status" aria-label="File info">
      <span className="ui-code-meta"><DatabaseIcon size={12} />{formatSize(bytes)}</span>
      <span className="ui-code-meta"><ListIcon size={12} />{lines} {lines === 1 ? "line" : "lines"}</span>
      <span className="ui-code-meta"><CodeIcon size={12} />{languageLabel(grammar)}</span>
      <span className="ui-code-meta"><TypeIcon size={12} />UTF-8</span>
      <span className="ui-code-meta ui-code-readonly"><LockIcon size={12} />Read-only</span>
    </div>
  )
}

export function CodeViewer({ code, language = "", highlight = false, marks = [], emptyText = "No content to show" }: CodeViewerProps) {
  const grammar = useMemo(() => resolveGrammar(language, highlight), [language, highlight])
  const marked = useMemo(() => buildMarkIndex(marks), [marks])
  const lines = useMemo(() => splitLines(code), [code])
  const [rendered, setRendered] = useState<number | null>(null)
  const [renderedFor, setRenderedFor] = useState(code)
  const renderGeneration = useRef(0)

  // Render-phase reset (not an effect): the first paint of a large file must
  // already be chunked, otherwise the full parse blocks before loading shows.
  if (renderedFor !== code) {
    setRenderedFor(code)
    setRendered(lines.length > PROGRESSIVE_THRESHOLD ? PROGRESSIVE_CHUNK : null)
  }

  // Large files would block the main thread parsing hundreds of lines at
  // once, so above a threshold rows are appended in chunks while a progress
  // pill keeps the viewer responsive.
  useEffect(() => {
    renderGeneration.current += 1
    const token = renderGeneration.current
    void paint(token)

    async function paint(current: number) {
      const alive = () => renderGeneration.current === current
      if (lines.length <= PROGRESSIVE_THRESHOLD) {
        if (alive()) {
          setRendered(null)
        }
        return
      }
      let shown = PROGRESSIVE_CHUNK
      setRendered(shown)
      while (shown < lines.length && alive()) {
        await new Promise<void>((resolve) => setTimeout(resolve, 0))
        if (!alive()) {
          return
        }
        shown += PROGRESSIVE_CHUNK
        setRendered(shown >= lines.length ? null : shown)
      }
    }
  }, [code, lines.length])

  if (code === "") {
    return (
      <div className="ui-code-viewer">
        <FileBar code={code} grammar={grammar} />
        <p className="label ui-code-empty">{emptyText}</p>
      </div>
    )
  }

  const visible = rendered === null ? lines : lines.slice(0, rendered)

  return (
    <div className="ui-code-viewer">
      <FileBar code={code} grammar={grammar} />
      <pre className="ui-code-body" aria-label="File content">
        <code>
          {visible.map((line, index) => (
            // index keys are safe: lines never reorder, insert or delete
            <CodeLine
              key={index}
              line={line}
              number={index + 1}
              grammar={grammar}
              mark={marked.get(index + 1) ?? null}
            />
          ))}
        </code>
      </pre>
      {rendered !== null && (
        <div className="ui-code-progress" role="status" aria-label="Loading file content">
          <Spinner size={12} tone="light" />
          <span>{Math.round((rendered / lines.length) * 100)}%</span>
        </div>
      )}
    </div>
  )
}
