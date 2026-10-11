import { useEffect, useId, useState } from "react"
import type mermaidApi from "mermaid"
import "./MermaidDiagram.css"

// Loaded on demand: mermaid is heavy (~2MB) and only diagram pages need it,
// so the main bundle stays lean and the chunk loads when one renders.
let api: typeof mermaidApi | null = null

async function loadMermaid(): Promise<typeof mermaidApi> {
  if (api === null) {
    const module = await import("mermaid")
    module.default.initialize({ startOnLoad: false, theme: "default", securityLevel: "strict" })
    api = module.default
  }
  return api
}

/** Renders a Mermaid chart to SVG, falling back to its source on failure.
 *
 * Diagrams arrive as model-adjacent strings (derived, but worth distrusting
 * like any agent output): a chart that does not parse shows its source
 * instead of a blank box, so it stays inspectable either way.
 */
export function MermaidDiagram({ chart, label }: { chart: string; label: string }) {
  const rawId = useId()
  const [rendered, setRendered] = useState<{ chart: string; svg: string } | null>(null)
  const [failedFor, setFailedFor] = useState<string | null>(null)
  const renderId = `mermaid-${rawId.replace(/[^A-Za-z0-9_-]/g, "")}`

  useEffect(() => {
    let alive = true
    void loadMermaid().then(
      (mermaid) => mermaid.render(renderId, chart)
    ).then(
      (result) => {
        if (alive) {
          setRendered({ chart, svg: result.svg })
        }
      },
      () => {
        if (alive) {
          setFailedFor(chart)
        }
      }
    )
    return () => {
      alive = false
    }
  }, [renderId, chart])

  if (failedFor === chart) {
    return <pre className="ui-mermaid-fallback">{chart}</pre>
  }

  if (rendered !== null && rendered.chart === chart) {
    return <div className="ui-mermaid" role="img" aria-label={label} dangerouslySetInnerHTML={{ __html: rendered.svg }} />
  }

  return <p className="label">Rendering diagram</p>
}
