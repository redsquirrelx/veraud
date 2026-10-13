import { readFile } from "node:fs/promises"
import { createRequire } from "node:module"
import { dirname, join } from "node:path"

interface PortalAsset {
  name: string
  body: Buffer
  contentType: string
}

const require = createRequire(import.meta.url)
const componentRoot = dirname(require.resolve("@asyncapi/react-component/package.json"))
const assetDefinitions = [
  { name: "asyncapi.js", path: join(componentRoot, "browser/standalone/index.js"), contentType: "application/javascript" },
  { name: "index.js.LICENSE.txt", path: join(componentRoot, "browser/standalone/index.js.LICENSE.txt"), contentType: "text/plain" },
  { name: "asyncapi.css", path: join(componentRoot, "styles/default.min.css"), contentType: "text/css" },
  { name: "portal.js", path: new URL("./portal/portal.js", import.meta.url), contentType: "application/javascript" },
  { name: "portal.css", path: new URL("./portal/portal.css", import.meta.url), contentType: "text/css" },
] as const

let cachedAssets: Promise<PortalAsset[]> | undefined

/** Cache scripts/styles per process; read HTML and generated YAML at app startup. */
export async function loadPortalResources() {
  cachedAssets ??= Promise.all(assetDefinitions.map(async ({ name, path, contentType }) => ({
    name,
    contentType,
    body: await readFile(path),
  })))

  const [html, specification, assets] = await Promise.all([
    readFile(new URL("./portal/index.html", import.meta.url), "utf8"),
    readFile(new URL("./asyncapi.yaml", import.meta.url), "utf8"),
    cachedAssets,
  ])

  return { html, specification, assets }
}
