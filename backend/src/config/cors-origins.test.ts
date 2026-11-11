import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { normalizeCorsOrigins } from "./cors-origins.js"

describe("CORS origin normalization", () => {
  it("adds https to a bare Cloudflare Quick Tunnel hostname", () => {
    assert.deepEqual(
      normalizeCorsOrigins(["mi-tunel.trycloudflare.com"]),
      ["https://mi-tunel.trycloudflare.com"],
    )
  })

  it("removes trailing slashes and paths", () => {
    assert.deepEqual(
      normalizeCorsOrigins(["https://mi-tunel.trycloudflare.com/", "https://otro.example.com/path?q=1"]),
      ["https://mi-tunel.trycloudflare.com", "https://otro.example.com"],
    )
  })

  it("uses http for local development hosts", () => {
    assert.deepEqual(
      normalizeCorsOrigins(["localhost:5173", "127.0.0.1:3000", "[::1]:4173"]),
      ["http://localhost:5173", "http://127.0.0.1:3000", "http://[::1]:4173"],
    )
  })

  it("accepts comma-separated values, trims, and deduplicates", () => {
    assert.deepEqual(
      normalizeCorsOrigins([" https://uno.example.com , https://dos.example.com/ ", "https://UNO.example.com"]),
      ["https://uno.example.com", "https://dos.example.com"],
    )
  })

  it("ignores blanks and invalid entries", () => {
    assert.deepEqual(normalizeCorsOrigins(["", "   ", "not a url", "https://ok.example.com"]), [
      "https://ok.example.com",
    ])
  })
})
