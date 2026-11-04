import { useState } from "react"
import { useTranslation } from "react-i18next"
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
  const { t } = useTranslation("common")
  const [revision, setRevision] = useState(0)

  async function reload() {
    await new Promise<void>((resolve) => {
      setTimeout(resolve, 600)
    })
    setRevision((current) => current + 1)
  }

  return (
    <section className="test-directory-page ui-page-stack">
      <h1>{t("testPages.directory.title")}</h1>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.directory.projectStructure")}</span>
        <DirectoryTree
          tree={mockTree}
          initialExpanded={["payment-gateway-v2/src", "payment-gateway-v2/src/modules"]}
          initialSelected="payment-gateway-v2/src/modules/ledger.repository.ts"
        />
      </Card>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.directory.grouped")}</span>
        <DirectoryTree
          tree={mockTree}
          groups={groups}
          initialExpanded={openNested}
          initialSelected="payment-gateway-v2/src/modules/reconciliation/engine.ts"
        />
      </Card>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.directory.groupsPlusFindings", { count: flagged.length })}</span>
        <DirectoryTree
          tree={mockTree}
          groups={groups}
          flaggedPaths={flagged}
          initialExpanded={openNested}
          initialSelected="payment-gateway-v2/src/modules/reconciliation/engine.ts"
        />
      </Card>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.directory.flaggedOnly", { count: flagged.length })}</span>
        <DirectoryTree
          tree={mockTree}
          flaggedPaths={flagged}
          initialExpanded={openNested}
          initialSelected="payment-gateway-v2/src/modules/reconciliation/engine.ts"
        />
      </Card>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.directory.reloading", { revision })}</span>
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
