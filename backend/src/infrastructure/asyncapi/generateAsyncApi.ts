import { writeFile } from "node:fs/promises"
import { asyncApiFile, serializeAsyncApi } from "./serializeAsyncApi.js"

await writeFile(asyncApiFile, serializeAsyncApi(), "utf8")
console.log("Generated asyncapi.yaml from shared TypeScript contracts.")
