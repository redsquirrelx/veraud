import { describe, expect, it } from "vitest"
// @ts-expect-error Node file access is intentionally scoped to this Vitest-only test.
import { readFileSync } from "node:fs"

// JSDOM gives import.meta.url an HTTP origin, so resolve the source stylesheet from Vitest's frontend working directory.
const tokenSource = readFileSync("src/shared/styles/tokens.css", "utf8")
const tokens = new Map<string, string>([...tokenSource.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)]
  .map(([, name, value]) => [name!, value!.trim()] as const))

function resolve(name: string, chain = new Set<string>()): string {
  if (chain.has(name)) throw new Error(`Cyclic color token alias: ${name}`)
  const value = tokens.get(name)
  if (value === undefined) throw new Error(`Missing color token: ${name}`)
  const alias = /^var\((--[\w-]+)\)$/.exec(value)
  if (alias) return resolve(alias[1]!, new Set([...chain, name]))
  return value
}

function rgb(token: string): [number, number, number] {
  const value = resolve(token)
  const hex = /^#([\da-f]{3}|[\da-f]{6})$/i.exec(value)
  if (!hex) throw new Error(`${token} must resolve to an opaque hex color; got ${value}`)
  const digits = hex[1]!.length === 3 ? [...hex[1]!].map((digit) => digit + digit).join("") : hex[1]!
  return [0, 2, 4].map((offset) => parseInt(digits.slice(offset, offset + 2), 16)) as [number, number, number]
}

function luminance(token: string): number {
  const [red, green, blue] = rgb(token).map((channel) => {
    const value = channel / 255
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * red! + 0.7152 * green! + 0.0722 * blue!
}

function contrast(foreground: string, background: string): number {
  const first = luminance(foreground)
  const second = luminance(background)
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05)
}

type ContrastPair = [foreground: string, background: string]

function crossPairs(foregrounds: string[], backgrounds: string[]): ContrastPair[] {
  return foregrounds.flatMap((foreground) => backgrounds.map((background): ContrastPair => [foreground, background]))
}

const textPairs: ContrastPair[] = [
  ...crossPairs(
    ["--color-text", "--color-text-secondary", "--color-text-description", "--color-text-muted", "--color-text-placeholder"],
    ["--color-surface", "--color-canvas", "--color-surface-tint", "--color-surface-hover", "--color-surface-active"],
  ),
  ...["--color-brand", "--color-brand-hover", "--color-brand-active"].flatMap((background) => [
    ["--color-on-brand", background] as ContrastPair, ["--color-text-inverse", background] as ContrastPair,
  ]),
  ...["success", "warning", "info", "neutral", "danger", "unknown"].map((tone): ContrastPair => [
    `--status-${tone}-text`, `--status-${tone}-bg`,
  ]),
  ["--color-text-inverse", "--status-danger-solid"],
  ["--color-text-inverse", "--status-warning-solid"],
  ["--color-text-inverse", "--status-info-solid"],
  ["--color-text-inverse", "--color-text"],
  ["--color-highlight-text", "--color-highlight-bg"],
]

const graphicPairs: ContrastPair[] = [
  ...crossPairs(
    ["--color-border-control", "--color-focus", "--color-selection-border"],
    ["--color-surface", "--color-canvas", "--color-surface-tint", "--color-selection-soft", "--color-surface-hover", "--color-surface-active"],
  ),
  ["--status-success-dot", "--status-success-bg"],
  ["--status-danger-dot", "--status-danger-bg"],
  ["--status-unknown-dot", "--status-unknown-bg"],
  ["--status-success-accent", "--status-success-bg"],
  ["--status-running-accent", "--status-info-bg"],
  ["--status-info-accent", "--status-info-bg"],
  ["--status-partial-accent", "--status-warning-bg"],
  ["--status-failed-accent", "--status-danger-bg"],
]

describe("semantic color contrast tokens", () => {
  it.each(textPairs)("keeps %s at WCAG AA normal-text contrast on %s", (foreground, background) => {
    expect(contrast(foreground, background), `${foreground} on ${background}`).toBeGreaterThanOrEqual(4.5)
  })

  it.each(graphicPairs)("keeps %s distinguishable at 3:1 on %s", (foreground, background) => {
    expect(contrast(foreground, background), `${foreground} on ${background}`).toBeGreaterThanOrEqual(3)
  })
})
