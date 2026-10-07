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
    <section className="test-file-viewer-page">
      <h1>File viewer playground</h1>
      <Card>
        <span className="label">payment-gateway-v2/src/modules/settlement.ts ({lines} lines)</span>
        <CodeViewer code={sample} />
      </Card>
      <Card>
        <span className="label">payment-gateway-v2/src/modules/settlement.ts with agent marks</span>        <CodeViewer
          code={sample}
          language="ts"
          highlight
          marks={[
            { id: "A", from: 8, to: 9, tone: "danger", note: "unvalidated amount reaches settle" },
            { id: "B", from: 12, to: 12, tone: "warning", note: "currency normalization" },
            { id: "C", from: 1, to: 5, tone: "info", note: "plain data shape" },
          ]}
        />
        <CodeExplanations
          items={[
            { id: "A", tone: "danger", title: "Unvalidated amount", body: "Lines 8 to 9 throw a generic error instead of a domain one." },
            { id: "B", tone: "warning", title: "Currency normalization", body: "Line 12 uppercases in place; consider a value object." },
            { id: "C", tone: "info", title: "Plain data shape", body: "Lines 1 to 5 carry no behaviour, safe to extend." },
          ]}
        />
      </Card>
      <Card>
        <span className="label">payment-gateway-v2/src/modules/settlement.ts grouped by finding</span>
        <CodeViewer
          code={sample}
          language="ts"
          highlight
          marks={[
            { id: "D", from: 2, to: 4, tone: "warning", note: "untyped shape" },
            { id: "D", from: 7, to: 9, tone: "warning", note: "untyped shape" },
          ]}
        />
        <CodeExplanations
          items={[
            { id: "D", tone: "warning", title: "Missing domain types", body: "Lines 2 to 4 and 7 to 9 repeat the same structural smell in two places." },
          ]}
        />
      </Card>
      <Card>
        <span className="label">Empty file</span>
        <CodeViewer code="" />
      </Card>
      <Card>
        <span className="label">payment-gateway-v2/src/generated/ledger-entries.ts ({longLines} lines)</span>
        <CodeViewer code={longSample} />
      </Card>
      <Card>
        <span className="label">payment-gateway-v2/src/settle.py (highlighted)</span>
        <CodeViewer code={pythonSample} language="py" highlight />
      </Card>
      <Card>
        <span className="label">payment-gateway-v2/src/modules/settlement.highlighted.ts (highlighted)</span>
        <CodeViewer code={sample} language="ts" highlight />
      </Card>
      <Card>
        <span className="label">payment-gateway-v2/src/charge.js (highlighted)</span>
        <CodeViewer code={jsSample} language="js" highlight />
      </Card>
      <Card>
        <span className="label">payment-gateway-v2/config.json (highlighted)</span>
        <CodeViewer code={jsonSample} language="json" highlight />
      </Card>
      <Card>
        <span className="label">payment-gateway-v2/scripts/deploy.sh (highlighted)</span>
        <CodeViewer code={shellSample} language="sh" highlight />
      </Card>
      <Card>
        <span className="label">payment-gateway-v2/dist/bundle.min.json (long lines)</span>
        <CodeViewer code={longLinesSample} language="json" highlight />
      </Card>
    </section>
  )
}
