import { useTranslation } from "react-i18next"
import { Card, CodeExplanations, CodeViewer } from "../../shared/ui-kit/index.ts"
import "./TestFileViewerPage.css"

const sample = `export interface Settlement {
  id: string
  amount: number
  currency: string
}

export function settle(payment: Settlement): Settlement {
  if (payment.amount <= 0) {
    throw new Error("amount must be positive")
  }

  return { ...payment, currency: payment.currency.toUpperCase() }
}
`

const pythonSample = `import os

DEFAULT_CURRENCY = "USD"


def settle(payment):
    if payment["amount"] <= 0:
        raise ValueError("amount must be positive")

    return {**payment, "currency": os.getenv("CURRENCY", DEFAULT_CURRENCY)}
`

const jsSample = `const gateway = require("./gateway")

async function charge(payment) {
  if (payment === null || typeof payment.amount !== "number") {
    throw new Error("invalid payment")
  }

  const receipt = await gateway.charge(payment)
  return receipt.id
}

module.exports = { charge }
`

const jsonSample = `{
  "name": "payment-gateway",
  "live": true,
  "retries": 3,
  "fallback": null,
  "debug": false
}
`

const shellSample = `#!/bin/sh
set -eu

if [ "$1" = "prod" ]; then
  echo "deploying prod"
  exit 0
fi

for region in us eu; do
  echo "$region"
done
`

const longLinesSample = `{"ledger":{"entries":[${Array.from({ length: 40 }, (_, index) => `{"id":${index + 1},"amount":${((index + 1) * 13) % 997},"currency":"USD"}`).join(",")}],"cursor":"${"0123456789abcdef".repeat(32)}"}}
${"abcdefghijklmnopqrstuvwxyz0123456789".repeat(48)}
short line
`

export function TestFileViewerPage() {
  const { t } = useTranslation("common")
  const lines = sample.replace(/\n$/, "").split("\n").length
  const longSample = Array.from({ length: 120 }, (_, index) => {
    const line = index + 1
    if (line % 10 === 0 && line < 120) {
      return ""
    }
    if (line % 10 === 1) {
      return `// batch ${Math.floor(index / 10) + 1}: generated ledger entries`
    }
    return `export const entry${String(line).padStart(3, "0")} = { id: ${line}, amount: ${(line * 13) % 997}, currency: "USD" }`
  }).join("\n")
  const longLines = longSample.split("\n").length

  return (
    <section className="test-file-viewer-page ui-page-stack">
      <h1>{t("testPages.fileViewer.title")}</h1>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.fileViewer.fileLines", { file: "payment-gateway-v2/src/modules/settlement.ts", count: lines })}</span>
        <CodeViewer code={sample} />
      </Card>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.fileViewer.withMarks", { file: "payment-gateway-v2/src/modules/settlement.ts" })}</span>        <CodeViewer
          code={sample}
          language="ts"
          highlight
          marks={[
            { id: "A", from: 8, to: 9, tone: "danger", note: t("testPages.fileViewer.findings.A.note") },
            { id: "B", from: 12, to: 12, tone: "warning", note: t("testPages.fileViewer.findings.B.note") },
            { id: "C", from: 1, to: 5, tone: "info", note: t("testPages.fileViewer.findings.C.note") },
          ]}
        />
        <CodeExplanations
          items={[
            { id: "A", tone: "danger", title: t("testPages.fileViewer.findings.A.title"), body: t("testPages.fileViewer.findings.A.body") },
            { id: "B", tone: "warning", title: t("testPages.fileViewer.findings.B.title"), body: t("testPages.fileViewer.findings.B.body") },
            { id: "C", tone: "info", title: t("testPages.fileViewer.findings.C.title"), body: t("testPages.fileViewer.findings.C.body") },
          ]}
        />
      </Card>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.fileViewer.groupedByFinding", { file: "payment-gateway-v2/src/modules/settlement.ts" })}</span>
        <CodeViewer
          code={sample}
          language="ts"
          highlight
          marks={[
            { id: "D", from: 2, to: 4, tone: "warning", note: t("testPages.fileViewer.findings.D.note") },
            { id: "D", from: 7, to: 9, tone: "warning", note: t("testPages.fileViewer.findings.D.note") },
          ]}
        />
        <CodeExplanations
          items={[
            { id: "D", tone: "warning", title: t("testPages.fileViewer.findings.D.title"), body: t("testPages.fileViewer.findings.D.body") },
          ]}
        />
      </Card>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.fileViewer.emptyFile")}</span>
        <CodeViewer code="" />
      </Card>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.fileViewer.fileLines", { file: "payment-gateway-v2/src/generated/ledger-entries.ts", count: longLines })}</span>
        <CodeViewer code={longSample} />
      </Card>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.fileViewer.highlightedFile", { file: "payment-gateway-v2/src/settle.py" })}</span>
        <CodeViewer code={pythonSample} language="py" highlight />
      </Card>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.fileViewer.highlightedFile", { file: "payment-gateway-v2/src/modules/settlement.highlighted.ts" })}</span>
        <CodeViewer code={sample} language="ts" highlight />
      </Card>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.fileViewer.highlightedFile", { file: "payment-gateway-v2/src/charge.js" })}</span>
        <CodeViewer code={jsSample} language="js" highlight />
      </Card>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.fileViewer.highlightedFile", { file: "payment-gateway-v2/config.json" })}</span>
        <CodeViewer code={jsonSample} language="json" highlight />
      </Card>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.fileViewer.highlightedFile", { file: "payment-gateway-v2/scripts/deploy.sh" })}</span>
        <CodeViewer code={shellSample} language="sh" highlight />
      </Card>
      <Card layout="stack" gap="sm" align="start">
        <span className="label">{t("testPages.fileViewer.longLinesFile", { file: "payment-gateway-v2/dist/bundle.min.json" })}</span>
        <CodeViewer code={longLinesSample} language="json" highlight />
      </Card>
    </section>
  )
}
