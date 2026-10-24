import { useState } from "react"
import { useTranslation } from "react-i18next"
import { Button, Card, FilterTabs, Panel, RefreshButton, SortButton, Spinner, TextInput, Toast, useAsyncAction } from "../../shared/ui-kit/index.ts"
import "./ComponentTestPage.css"

function waitASecond() {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, 1000)
  })
}

const filterOptionKeys = [
  { id: "all", labelKey: "testPages.components.filters.all", count: 18 },
  { id: "running", labelKey: "testPages.components.filters.running", count: 2 },
  { id: "approved", labelKey: "testPages.components.filters.approved", count: 12 },
  { id: "vulnerable", labelKey: "testPages.components.filters.vulnerable", count: 4 },
] as const

export function ComponentTestPage() {
  const { t } = useTranslation("common")
  const [url, setUrl] = useState("https://github.com/fintech-core/payment-gateway-v2")
  const [filter, setFilter] = useState("all")
  const [direction, setDirection] = useState<"asc" | "desc">("asc")
  const [notice, setNotice] = useState<string | null>(null)
  const filterOptions = filterOptionKeys.map((option) => ({ id: option.id, label: t(option.labelKey), count: option.count }))
  const slowSave = useAsyncAction(() => waitASecond())
  const notify = useAsyncAction(async () => {
    await waitASecond()
    setNotice(t("testPages.components.projectRegistered"))
  })
  const refresh = useAsyncAction(() => waitASecond())
  const hanging = useAsyncAction(() => new Promise<void>(() => {}), { timeoutMs: 3000 })

  return (
    <section className="page">
      <h1>{t("testPages.components.title")}</h1>

      <h2>{t("testPages.components.containers")}</h2>
      <Card>
        <span className="label">{t("testPages.components.cardSurface")}</span>
        <div className="playground-row">
          <Button>{t("testPages.components.registerProject")}</Button>
          <TextInput value={url} placeholder="https://github.com/owner/repo" onChange={setUrl} />
        </div>
      </Card>
      <Panel>
        <span className="label">{t("testPages.components.panelSurface")}</span>
        <div className="playground-row">
          <Button loading>{t("testPages.components.registering")}</Button>
          <Toast kind="success" message={t("testPages.components.projectRegistered")} />
        </div>
      </Panel>

      <h2>{t("testPages.components.button")}</h2>
      <div className="playground-row">
        <Button>{t("testPages.components.registerProject")}</Button>
        <Button disabled>{t("testPages.components.disabled")}</Button>
        <Button loading>{t("testPages.components.registering")}</Button>
      </div>

      <h2>{t("testPages.components.textInput")}</h2>
      <div className="playground-row">
        <TextInput value={url} placeholder="https://github.com/owner/repo" onChange={setUrl} />
        <TextInput value="" placeholder={t("testPages.components.empty")} onChange={() => {}} />
        <TextInput value="locked" onChange={() => {}} disabled />
      </div>

      <h2>{t("testPages.components.toast")}</h2>
      <div className="playground-row">
        <Toast kind="success" message={t("testPages.components.projectRegistered")} />
        <Toast kind="error" message={t("testPages.components.repositoryNotAccessible")} />
      </div>

      <h2>{t("testPages.components.combined")}</h2>
      <Panel>
        <span className="label">{t("testPages.components.toolbarStrip")}</span>
        <div className="playground-row">
          <TextInput value={url} placeholder="https://github.com/owner/repo" onChange={setUrl} />
          <Button>{t("testPages.components.cloneAndIngest")}</Button>
        </div>
      </Panel>
      <Card>
        <span className="label">{t("testPages.components.projectRow")}</span>
        <span className="mono">core-settlement-engine</span>
        <div className="playground-row">
          <Button>{t("testPages.components.inspect")}</Button>
          <Toast kind="success" message={t("testPages.components.auditFinished")} />
        </div>
      </Card>
      <Card>
        <Panel>
          <span className="label">{t("testPages.components.cardNestingPanel")}</span>
          <div className="playground-row">
            <TextInput value="" placeholder={t("testPages.components.filterByRepository")} onChange={() => {}} />
            <Toast kind="error" message={t("testPages.components.cloneFailed")} />
          </div>
        </Panel>
      </Card>
      <Panel>
        <span className="label">{t("testPages.components.panelNestingCards")}</span>
        <div className="playground-stack">
          <Card>
            <span className="mono">fintech-ledger-api</span>
            <div className="playground-row">
              <Button>{t("testPages.components.inspect")}</Button>
            </div>
          </Card>
          <Card>
            <span className="mono">auth-oauth2-microservice</span>
            <div className="playground-row">
              <Button disabled>{t("testPages.components.auditing")}</Button>
              <Toast kind="error" message={t("testPages.components.cveFound")} />
            </div>
          </Card>
        </div>
      </Panel>

      <h2>{t("testPages.components.filterBar")}</h2>
      <Panel>
        <div className="playground-row">
          <TextInput value="" placeholder={t("testPages.components.filterByRepoTags")} onChange={() => {}} />
          <FilterTabs options={filterOptions} value={filter} onChange={setFilter} />
          <SortButton direction={direction} onToggle={() => setDirection(direction === "asc" ? "desc" : "asc")} />
          <RefreshButton onClick={() => {}} />
        </div>
      </Panel>

      <h2>{t("testPages.components.loading")}</h2>
      <div className="playground-row">
        <Spinner />
        <RefreshButton loading onClick={() => {}} />
      </div>
      <h2>{t("testPages.components.statusLabels")}</h2>
      <Panel>
        <span className="label">{t("testPages.components.syncingRepository")}</span>
      </Panel>
      <Card>
        <span className="label">{t("testPages.components.auditInProgress")}</span>
      </Card>

      <h2>{t("testPages.components.asyncButtons")}</h2>
      <div className="playground-row">
        <Button loading={slowSave.loading} onClick={() => void slowSave.run()}>
          {t("testPages.components.save1s")}
        </Button>
        <Button loading={notify.loading} onClick={() => void notify.run()}>
          {t("testPages.components.notify")}
        </Button>
        <RefreshButton loading={refresh.loading} onClick={() => void refresh.run()} />
        <Button loading={hanging.loading} onClick={() => void hanging.run()}>
          {t("testPages.components.hang3s")}
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

      <h2>{t("testPages.components.typography")}</h2>      <div className="playground-column">
        <span className="label">{t("testPages.components.headlineLabel")}</span>
        <span className="playground-headline">{t("testPages.components.typographyTitle")}</span>
        <span className="label">{t("testPages.components.bodyLabel")}</span>
        <span>{t("testPages.components.typographyBody")}</span>
        <span className="label">{t("testPages.components.repoNameLabel")}</span>
        <span className="mono">fintech-core/payment-gateway-v2</span>
        <span className="label">{t("testPages.components.commitLabel")}</span>
        <span className="mono">commit #8fbc2a1 ┬╖ feat(settle): parallel ledger</span>
      </div>
    </section>
  )
}
