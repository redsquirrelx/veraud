import hljs from "highlight.js/lib/core"
import typescript from "highlight.js/lib/languages/typescript"
import javascript from "highlight.js/lib/languages/javascript"
import python from "highlight.js/lib/languages/python"
import json from "highlight.js/lib/languages/json"
import bash from "highlight.js/lib/languages/bash"

hljs.registerLanguage("typescript", typescript)
hljs.registerLanguage("javascript", javascript)
hljs.registerLanguage("python", python)
hljs.registerLanguage("json", json)
hljs.registerLanguage("bash", bash)

export type CodeMarkTone = "danger" | "warning" | "info"

export interface CodeViewerMark {
  id: string
  from: number
  to: number
  tone: CodeMarkTone
  note?: string
}

export interface CodeExplanation {
  id: string
  tone: CodeMarkTone
  title: string
  body: string
}

export interface LineMark {
  id: string
  tone: CodeMarkTone
  first: boolean
  note?: string
}

const LANGUAGE_OF: Record<string, string> = {
  ts: "typescript",
  js: "javascript",
  py: "python",
  json: "json",
  sh: "bash",
}

const LANGUAGE_LABEL: Record<string, string> = {
  typescript: "TypeScript",
  javascript: "JavaScript",
  python: "Python",
  json: "JSON",
  bash: "Shell",
}

const ROW_CLASS_OF: Record<CodeMarkTone, string> = {
  danger: "ui-code-line ui-code-line-danger",
  warning: "ui-code-line ui-code-line-warning",
  info: "ui-code-line ui-code-line-info",
}

// A single trailing newline is a file terminator, not an extra blank line.
export function splitLines(code: string): string[] {
  if (code === "") {
    return []
  }
  return code.replace(/\n$/, "").split("\n")
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`
  }
  return `${(bytes / 1024).toFixed(1)} KB`
}

export function resolveGrammar(language: string, highlight: boolean): string | null {
  if (!highlight) {
    return null
  }
  return LANGUAGE_OF[language.toLowerCase()] ?? null
}

export function languageLabel(grammar: string | null): string {
  if (grammar === null) {
    return "Plain text"
  }
  return LANGUAGE_LABEL[grammar] ?? grammar
}

// Highlight.js works on whole documents, so a token spanning several lines
// (block comment, multiline string) is approximated per line. Good enough
// for a read-only viewer; a precise renderer would need span tracking.
export function highlightLine(line: string, grammar: string | null): string | null {
  if (line === "" || grammar === null || hljs.getLanguage(grammar) === undefined) {
    return null
  }
  return hljs.highlight(line, { language: grammar }).value
}

// Expands ranges into a per-line lookup. Lines are 1-based, invalid ranges
// are dropped, and the first mark wins on overlap so output is stable.
export function buildMarkIndex(marks: CodeViewerMark[]): Map<number, LineMark> {
  const indexed = new Map<number, LineMark>()

  for (const mark of marks) {
    if (!Number.isInteger(mark.from) || !Number.isInteger(mark.to) || mark.from < 1 || mark.to < mark.from) {
      continue
    }
    for (let line = mark.from; line <= mark.to; line += 1) {
      if (!indexed.has(line)) {
        indexed.set(line, { id: mark.id, tone: mark.tone, first: line === mark.from, note: mark.note })
      }
    }
  }

  return indexed
}

export function rowClassName(mark: LineMark | null): string {
  if (mark === null) {
    return "ui-code-line"
  }
  return ROW_CLASS_OF[mark.tone]
}
