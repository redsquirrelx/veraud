import { afterEach } from "vitest"
import { cleanup } from "@testing-library/react"
import "@testing-library/jest-dom/vitest"
import { initializeI18n } from "./shared/i18n/index.ts"

// Deterministic English baseline for every test file. Files that exercise
// other languages re-initialize explicitly within their own tests.
await initializeI18n("en")

afterEach(() => {
  cleanup()
})
