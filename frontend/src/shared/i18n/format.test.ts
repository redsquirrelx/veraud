import { beforeAll, beforeEach, describe, expect, it } from "vitest"
import { formatDate, formatDateTime, formatNumber, getLocale } from "./format.ts"
import { initializeI18n } from "./index.ts"

beforeAll(async () => {
  await initializeI18n("en")
})

beforeEach(async () => {
  await initializeI18n("en")
})

describe("format", () => {
  it("follows the active language", async () => {
    expect(getLocale()).toBe("en")
    await initializeI18n("es")
    expect(getLocale()).toBe("es")
  })

  it("groups numbers per locale", async () => {
    expect(formatNumber(1234567.891)).toBe("1,234,567.891")
    await initializeI18n("es")
    expect(formatNumber(1234567.891)).toBe("1.234.567,891")
  })

  it("applies caller-provided number options in both locales", async () => {
    expect(formatNumber(12.34, { maximumFractionDigits: 1 })).toBe("12.3")
    await initializeI18n("es")
    expect(formatNumber(12.34, { maximumFractionDigits: 1 })).toBe("12,3")
  })

  it("renders dates per locale", async () => {
    const en = formatDate("2026-01-15T12:00:00Z")
    await initializeI18n("es")
    const es = formatDate("2026-01-15T12:00:00Z")
    expect(en).not.toBe(es)
    expect(en).toContain("2026")
    expect(es).toContain("2026")
  })

  it("renders date and time per locale", async () => {
    const en = formatDateTime("2026-01-15T12:00:00Z")
    await initializeI18n("es")
    const es = formatDateTime("2026-01-15T12:00:00Z")
    expect(en).not.toBe(es)
    expect(en).toContain("2026")
    expect(es).toContain("2026")
  })
})
