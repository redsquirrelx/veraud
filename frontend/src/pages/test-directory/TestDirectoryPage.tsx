import { useState } from "react"
import { Card, DirectoryTree, type DirectoryGroup, type DirectoryTreeNode } from "../../shared/ui-kit/index.ts"
import "./TestDirectoryPage.css"

function buildTree(revision: number): DirectoryTreeNode {
  return {
    name: "payment-gateway-v2",
    children: [
    {
      name: "src",
      children: [
        {
          name: "modules",
          children: [
            { name: "settlement.ts" },
            { name: "ledger.repository.ts" },
            {
              name: "reconciliation",
              children: [{ name: "engine.ts" }, { name: "engine.test.ts" }],
            },
          ],
        },
        { name: "index.ts" },
        { name: "server.ts" },
      ],
    },
      { name: "package.json" },
      { name: "README.md" },
      { name: "tsconfig.json" },
      ...(revision > 0 ? [{ name: `generated-${revision}.ts` }] : []),
    ],
  }
}

const mockTree: DirectoryTreeNode = buildTree(0)

const groups: DirectoryGroup[] = [
  {
    id: "money",
    label: "critical",
    tone: "danger",
    paths: [
      "payment-gateway-v2/src/modules/reconciliation",
      "payment-gateway-v2/src/modules/reconciliation/engine.ts",
      "payment-gateway-v2/src/modules/settlement.ts",
    ],
  },
  {
    id: "infra",
    label: "infrastructure",
    tone: "info",
    paths: ["payment-gateway-v2/src/server.ts", "payment-gateway-v2/tsconfig.json"],
  },
  {
    id: "docs",
    label: "docs",
    tone: "success",
    paths: ["payment-gateway-v2/README.md"],
  },
]

const flagged = [
  "payment-gateway-v2/src/modules/reconciliation/engine.ts",
  "payment-gateway-v2/src/server.ts",
]

const openNested = [
  "payment-gateway-v2/src",
  "payment-gateway-v2/src/modules",
  "payment-gateway-v2/src/modules/reconciliation",
]

export function TestDirectoryPage() {
  const [revision, setRevision] = useState(0)

  async function reload() {
    await new Promise<void>((resolve) => {
      setTimeout(resolve, 600)
    })
    setRevision((current) => current + 1)
  }

  return (
    <section className="test-directory-page">
      <h1>Directory playground</h1>
      <Card>
        <span className="label">Project Structure</span>
        <DirectoryTree
          tree={mockTree}
          initialExpanded={["payment-gateway-v2/src", "payment-gateway-v2/src/modules"]}
          initialSelected="payment-gateway-v2/src/modules/ledger.repository.ts"
        />
      </Card>
      <Card>
        <span className="label">Grouped directories</span>
        <DirectoryTree
          tree={mockTree}
          groups={groups}
          initialExpanded={openNested}
          initialSelected="payment-gateway-v2/src/modules/reconciliation/engine.ts"
        />
      </Card>
      <Card>
        <span className="label">Groups plus agent findings ({flagged.length} flagged)</span>
        <DirectoryTree
          tree={mockTree}
          groups={groups}
          flaggedPaths={flagged}
          initialExpanded={openNested}
          initialSelected="payment-gateway-v2/src/modules/reconciliation/engine.ts"
        />
      </Card>
      <Card>
        <span className="label">Flagged only ({flagged.length} flagged, no groups)</span>
        <DirectoryTree
          tree={mockTree}
          flaggedPaths={flagged}
          initialExpanded={openNested}
          initialSelected="payment-gateway-v2/src/modules/reconciliation/engine.ts"
        />
      </Card>
      <Card>
        <span className="label">Reloading the directory (revision {revision})</span>
        <DirectoryTree
          tree={buildTree(revision)}
          groups={groups}
          flaggedPaths={flagged}
          initialExpanded={openNested}
          onRefresh={reload}
        />
      </Card>
      <DirectoryTree
        tree={buildTree(revision)}
        groups={groups}
        flaggedPaths={flagged}
        initialExpanded={openNested}
        initialSelected="payment-gateway-v2/src/modules/reconciliation/engine.test.ts"
        onRefresh={reload}
      />
    </section>
  )
}
