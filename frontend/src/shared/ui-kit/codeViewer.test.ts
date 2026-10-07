import { describe, expect, it } from "vitest"
import {
  buildMarkIndex,
  formatSize,
  highlightLine,
  languageLabel,
  resolveGrammar,
  rowClassName,
  splitLines,
} from "./codeViewer.ts"

describe("splitLines", () => {
  it("drops a single trailing newline but keeps blank lines", () => {
    expect(splitLines("")).toEqual([])
    expect(splitLines("only\n")).toEqual(["only"])
    expect(splitLines("first\n\nthird")).toEqual(["first", "", "third"])
  })
})

describe("formatSize", () => {
  it("uses bytes below a kilobyte", () => {
    expect(formatSize(0)).toBe("0 B")
    expect(formatSize(1023)).toBe("1023 B")
    expect(formatSize(1024)).toBe("1.0 KB")
    expect(formatSize(2048)).toBe("2.0 KB")
  })
})

describe("resolveGrammar", () => {
  it("maps extensions case-insensitively when highlighting", () => {
    expect(resolveGrammar("ts", true)).toBe("typescript")
    expect(resolveGrammar("TS", true)).toBe("typescript")
    expect(resolveGrammar("rs", true)).toBeNull()
    expect(resolveGrammar("ts", false)).toBeNull()
  })

  it("labels grammars for humans", () => {
    expect(languageLabel(null)).toBe("Plain text")
    expect(languageLabel("python")).toBe("Python")
    expect(languageLabel("mystery")).toBe("mystery")
  })
})

describe("highlightLine", () => {
  it("returns html only for known grammars and non-empty lines", () => {
    expect(highlightLine("", "typescript")).toBeNull()
    expect(highlightLine("const x = 1", null)).toBeNull()
    expect(highlightLine("const x = 1", "mystery")).toBeNull()
    expect(highlightLine("const x = 1", "typescript")).toContain("hljs-keyword")
  })
})

describe("buildMarkIndex", () => {
  it("expands ranges and keeps the first mark on overlap", () => {
    const indexed = buildMarkIndex([
      { id: "A", from: 2, to: 3, tone: "danger" },
      { id: "B", from: 3, to: 4, tone: "warning" },
      { id: "bad", from: 0, to: 2, tone: "info" },
      { id: "reversed", from: 5, to: 4, tone: "info" },
    ])

    expect(indexed.get(2)).toEqual({ id: "A", tone: "danger", first: true, note: undefined })
    expect(indexed.get(3)).toEqual({ id: "A", tone: "danger", first: false, note: undefined })
    expect(indexed.get(4)).toEqual({ id: "B", tone: "warning", first: false, note: undefined })
    expect(indexed.has(0)).toBe(false)
    expect(indexed.has(5)).toBe(false)
  })
})

describe("rowClassName", () => {
  it("combines the mark tone or falls back to plain", () => {
    expect(rowClassName(null)).toBe("ui-code-line")
    expect(rowClassName({ id: "A", tone: "danger", first: true })).toBe("ui-code-line ui-code-line-danger")
    expect(rowClassName({ id: "B", tone: "warning", first: false })).toBe("ui-code-line ui-code-line-warning")
    expect(rowClassName({ id: "C", tone: "info", first: true })).toBe("ui-code-line ui-code-line-info")
  })
})
