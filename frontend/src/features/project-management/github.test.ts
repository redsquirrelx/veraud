import { describe, expect, it } from "vitest"
import { githubRepoUrl } from "./github.ts"

describe("githubRepoUrl", () => {
  it("builds the public repository url", () => {
    expect(githubRepoUrl("acme", "Demo")).toBe("https://github.com/acme/Demo")
  })

  it("encodes unsafe characters", () => {
    expect(githubRepoUrl("acme org", "a&b")).toBe("https://github.com/acme%20org/a%26b")
  })
})
