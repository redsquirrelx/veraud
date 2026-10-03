import { afterEach, describe, it } from "node:test"
import assert from "node:assert/strict"
import { GithubClient, parseGithubUrl } from "./github.client.js"

const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

function stubFetch(status: number, body: unknown) {
  globalThis.fetch = (async () => {
    return new Response(JSON.stringify(body), { status })
  }) as typeof fetch
}

describe("parseGithubUrl", () => {
  it("parses a plain repo url", () => {
    assert.deepEqual(parseGithubUrl("https://github.com/octocat/Hello-World"), {
      owner: "octocat",
      repo: "Hello-World",
    })
  })

  it("trims .git suffix, slashes and extra path noise", () => {
    assert.deepEqual(parseGithubUrl("https://github.com/octocat/Hello-World.git/"), {
      owner: "octocat",
      repo: "Hello-World",
    })
  })

  it("rejects non-github hosts", () => {
    assert.equal(parseGithubUrl("https://gitlab.com/octocat/Hello-World"), null)
  })

  it("rejects urls without owner and repo", () => {
    assert.equal(parseGithubUrl("https://github.com/octocat"), null)
    assert.equal(parseGithubUrl("not-a-url"), null)
  })
})

describe("GithubClient.checkAccess", () => {
  it("returns metadata when the repo exists", async () => {
    stubFetch(200, { id: 1296269, name: "Hello-World", clone_url: "https://github.com/octocat/Hello-World.git" })

    const metadata = await new GithubClient().checkAccess("octocat", "Hello-World")

    assert.equal(metadata.id, 1296269)
    assert.equal(metadata.owner, "octocat")
    assert.equal(metadata.name, "Hello-World")
  })

  it("throws when the repo is missing", async () => {
    stubFetch(404, { message: "Not Found" })

    await assert.rejects(
      new GithubClient().checkAccess("octocat", "nope"),
      /not accessible/i
    )
  })
})
