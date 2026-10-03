import { useState } from "react"
import { Button, Card, FilterTabs, Panel, RefreshButton, SortButton, Spinner, TextInput, Toast, useAsyncAction } from "../../shared/ui-kit/index.ts"
import "./ComponentTestPage.css"

function waitASecond() {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, 1000)
  })
}

const filterOptions = [
  { id: "all", label: "All", count: 18 },
  { id: "running", label: "Running", count: 2 },
  { id: "approved", label: "Approved", count: 12 },
  { id: "vulnerable", label: "Vulnerable", count: 4 },
]

export function ComponentTestPage() {
  const [url, setUrl] = useState("https://github.com/fintech-core/payment-gateway-v2")
  const [filter, setFilter] = useState("all")
  const [direction, setDirection] = useState<"asc" | "desc">("asc")
  const [notice, setNotice] = useState<string | null>(null)
  const slowSave = useAsyncAction(() => waitASecond())
  const notify = useAsyncAction(async () => {
    await waitASecond()
    setNotice("Project registered")
  })
  const refresh = useAsyncAction(() => waitASecond())
  const hanging = useAsyncAction(() => new Promise<void>(() => {}), { timeoutMs: 3000 })

  return (
    <section>
      <h1>Component playground</h1>

      <h2>Containers</h2>
      <Card>
        <span className="label">Card / white surface</span>
        <div className="playground-row">
          <Button>Register project</Button>
          <TextInput value={url} placeholder="https://github.com/owner/repo" onChange={setUrl} />
        </div>
      </Card>
      <Panel>
        <span className="label">Panel / tinted surface</span>
        <div className="playground-row">
          <Button loading>Registering</Button>
          <Toast kind="success" message="Project registered" />
        </div>
      </Panel>

      <h2>Button</h2>
      <div className="playground-row">
        <Button>Register project</Button>
        <Button disabled>Disabled</Button>
        <Button loading>Registering</Button>
      </div>

      <h2>TextInput</h2>
      <div className="playground-row">
        <TextInput value={url} placeholder="https://github.com/owner/repo" onChange={setUrl} />
        <TextInput value="" placeholder="Empty" onChange={() => {}} />
        <TextInput value="locked" onChange={() => {}} disabled />
      </div>

      <h2>Toast</h2>
      <div className="playground-row">
        <Toast kind="success" message="Project registered" />
        <Toast kind="error" message="Repository is not accessible" />
      </div>

      <h2>Combined</h2>
      <Panel>
        <span className="label">Toolbar strip</span>
        <div className="playground-row">
          <TextInput value={url} placeholder="https://github.com/owner/repo" onChange={setUrl} />
          <Button>Clone and ingest</Button>
        </div>
      </Panel>
      <Card>
        <span className="label">Project row</span>
        <span className="mono">core-settlement-engine</span>
        <div className="playground-row">
          <Button>Inspect</Button>
          <Toast kind="success" message="Audit finished" />
        </div>
      </Card>
      <Card>
        <Panel>
          <span className="label">Card nesting a panel</span>
          <div className="playground-row">
            <TextInput value="" placeholder="Filter by repository" onChange={() => {}} />
            <Toast kind="error" message="Clone failed" />
          </div>
        </Panel>
      </Card>
      <Panel>
        <span className="label">Panel nesting cards</span>
        <div className="playground-stack">
          <Card>
            <span className="mono">fintech-ledger-api</span>
            <div className="playground-row">
              <Button>Inspect</Button>
            </div>
          </Card>
          <Card>
            <span className="mono">auth-oauth2-microservice</span>
            <div className="playground-row">
              <Button disabled>Auditing</Button>
              <Toast kind="error" message="CVE-2024-38819 found" />
            </div>
          </Card>
        </div>
      </Panel>

      <h2>Filter bar</h2>
      <Panel>
        <div className="playground-row">
          <TextInput value="" placeholder="Filtrar por repositorio, lenguaje o tags" onChange={() => {}} />
          <FilterTabs options={filterOptions} value={filter} onChange={setFilter} />
          <SortButton direction={direction} onToggle={() => setDirection(direction === "asc" ? "desc" : "asc")} />
          <RefreshButton onClick={() => {}} />
        </div>
      </Panel>

      <h2>Loading</h2>
      <div className="playground-row">
        <Spinner />
        <RefreshButton loading onClick={() => {}} />
      </div>
      <h2>Status labels</h2>
      <Panel>
        <span className="label">Syncing repository</span>
      </Panel>
      <Card>
        <span className="label">Audit in progress</span>
      </Card>

      <h2>Async buttons</h2>
      <div className="playground-row">
        <Button loading={slowSave.loading} onClick={() => void slowSave.run()}>
          Save (1s)
        </Button>
        <Button loading={notify.loading} onClick={() => void notify.run()}>
          Notify
        </Button>
        <RefreshButton loading={refresh.loading} onClick={() => void refresh.run()} />
        <Button loading={hanging.loading} onClick={() => void hanging.run()}>
          Hang (3s timeout)
        </Button>
      </div>
      {notice && (
        <div className="playground-row">
          <Toast kind="success" message={notice} onClose={() => setNotice(null)} />
        </div>
      )}
      {hanging.error && (
        <div className="playground-row">
          <Toast kind="error" message={hanging.error} />
        </div>
      )}

      <h2>Typography</h2>      <div className="playground-column">
        <span className="label">Geist / headline</span>
        <span className="playground-headline">Projects and Repositories</span>
        <span className="label">Geist / body</span>
        <span>Continuous autonomous supervision of quality attributes under ISO/IEC 25010.</span>
        <span className="label">JetBrains Mono / repository name</span>
        <span className="mono">fintech-core/payment-gateway-v2</span>
        <span className="label">JetBrains Mono / commit</span>
        <span className="mono">commit #8fbc2a1 ┬╖ feat(settle): parallel ledger</span>
      </div>
    </section>
  )
}
