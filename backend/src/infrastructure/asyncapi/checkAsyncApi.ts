import { readFile } from "node:fs/promises"
import { asyncApiFile, serializeAsyncApi } from "./serializeAsyncApi.js"

try {
  const current = await readFile(asyncApiFile, "utf8")
  // Git checkouts can use CRLF; compare content rather than platform line endings.
  if (current.replace(/\r\n/g, "\n") !== serializeAsyncApi()) {
    console.error("asyncapi.yaml is outdated. Run pnpm run docs:ws:generate.")
    process.exitCode = 1
  } else {
    console.log("asyncapi.yaml is synchronized with the shared TypeScript contracts.")
  }
} catch (error) {
  if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error
  console.error("asyncapi.yaml is missing. Run pnpm run docs:ws:generate.")
  process.exitCode = 1
}
