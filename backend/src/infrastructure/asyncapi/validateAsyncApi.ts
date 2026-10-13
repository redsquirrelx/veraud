import { readFile } from "node:fs/promises"
import { Parser } from "@asyncapi/parser"

const source = await readFile(new URL("./asyncapi.yaml", import.meta.url), "utf8")
const { document, diagnostics } = await new Parser().parse(source)

for (const diagnostic of diagnostics) {
  console.log(`[${diagnostic.severity}] ${diagnostic.code}: ${diagnostic.message}`)
}

if (!document || diagnostics.some((diagnostic) => diagnostic.severity === 0)) {
  process.exitCode = 1
} else {
  console.log(`AsyncAPI ${document.version()} valid: ${document.channels().length} channel(s), ${document.operations().length} operation(s).`)
}
