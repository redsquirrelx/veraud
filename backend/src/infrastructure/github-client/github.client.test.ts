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
      protocol: "https",
    })
  })

  it("trims .git suffix, slashes and extra path noise", () => {
    assert.deepEqual(parseGithubUrl("https://github.com/octocat/Hello-World.git/"), {
      owner: "octocat",
      repo: "Hello-World",
      protocol: "https",
    })
  })

  it("rejects non-github hosts", () => {
    assert.equal(parseGithubUrl("https://gitlab.com/octocat/Hello-World"), null)
  })

  it("accepts GitHub SSH URLs without consulting the public API", () => {
    for (const input of ["git@github.com:octocat/Hello-World.git", "ssh://git@github.com/octocat/Hello-World.git"]) {
      assert.deepEqual(parseGithubUrl(input), { owner: "octocat", repo: "Hello-World", protocol: "ssh" })
    }
  })

  it("rejects malformed and unexpected Git/SSH addresses", () => {
    for (const input of ["git@evil.com:octocat/Hello-World.git", "ssh://root@github.com/octocat/Hello-World.git", "git@github.com:octocat/../repo.git", "https://github.com/owner/repo?ref=main", "file:///owner/repo", "https://github.com/owner/repo/extra"]) {
      assert.equal(parseGithubUrl(input), null, input)
    }
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
