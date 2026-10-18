import { useState, type FormEvent } from "react"
import { useTranslation } from "react-i18next"
import { Badge, Button, Card, DropdownLinks, ExternalIcon, ItemList, ItemSearcher, ItemSelector, MinusIcon, Modal, PlusIcon, TextInput, type DropdownLinkItem, type ItemListEntry, type ItemSelectorItem } from "../../shared/ui-kit/index.ts"
import "./TestControlsPage.css"
import { DrawerExamples } from "./DrawerExamples.tsx"

const sampleItems: ItemSelectorItem[] = [
  { id: "openai", label: "OpenAI", detail: "3 models" },
  { id: "anthropic", label: "Anthropic", detail: "2 models" },
  { id: "google", label: "Google", detail: "1 model" },
]

const sampleEntries: ItemListEntry[] = [
  { id: "gpt-4o", name: "gpt-4o", description: "OpenAI flagship" },
  { id: "claude-3", name: "claude-3", description: "Anthropic model" },
  { id: "gemini-15", name: "gemini-1.5", description: "Google model" },
]

const backendUrl = (import.meta.env.VITE_BACKEND_URL ?? "http://localhost:7501").replace(/\/+$/, "")
const agentServerUrl = (import.meta.env.VITE_AGENT_SERVER_URL ?? "http://localhost:7502").replace(/\/+$/, "")

const navigationLinkKeys = [
  { labelKey: "navigation.home", href: "/" },
  { labelKey: "navigation.settings", href: "/settings" },
  { labelKey: "testPages.playgrounds", href: "/test" },
] as const

export function TestControlsPage() {
  const { t } = useTranslation("common")
  const documentationLinks: DropdownLinkItem[] = [
    { label: t("navigation.docs.backend"), href: `${backendUrl}/docs`, description: "HTTP API · Swagger", external: true },
    { label: t("navigation.docs.websocket"), href: `${backendUrl}/docs/ws`, description: "Realtime events · AsyncAPI", external: true },
    { label: t("navigation.docs.agentServer"), href: `${agentServerUrl}/docs`, description: "Agent HTTP API · Swagger", external: true },
  ]
  const navigationLinks: DropdownLinkItem[] = navigationLinkKeys.map((link) => ({ label: t(link.labelKey), href: link.href }))
  const [plain, setPlain] = useState("")
  const [model, setModel] = useState("")
  const [providerId, setProviderId] = useState<string | null>("openai")
  const [foundId, setFoundId] = useState<string | null>(null)
  const [formProviderId, setFormProviderId] = useState("openai")
  const [formModel, setFormModel] = useState("")
  const [submitted, setSubmitted] = useState<string | null>(null)
  const [count, setCount] = useState(0)
  const [picked, setPicked] = useState<string[]>(["gpt-4o"])
  const [favorite, setFavorite] = useState<string[]>(["gpt-4o"])
  const [modalOpen, setModalOpen] = useState(false)

  function submitForm(event: FormEvent) {
    event.preventDefault()
    const name = formModel.trim()
    if (name === "") {
      return
    }
    const provider = sampleItems.find((item) => item.id === formProviderId)?.label ?? formProviderId
    setSubmitted(`${provider} / ${name}`)
  }

  return (
    <section className="test-controls-page">
      <h1>{t("testPages.controls.title")}</h1>
      <Card>
        <span className="label">{t("testPages.controls.docsExternal")}</span>
        <p className="label">{t("testPages.controls.docsHint")}</p>
        <div className="test-controls-row">
          <DropdownLinks label={t("navigation.apiDocs")} icon={<ExternalIcon size={14} />} items={documentationLinks} />
        </div>
      </Card>
      <Card>
        <span className="label">{t("testPages.controls.navAlign")}</span>
        <div className="test-controls-row">
          <DropdownLinks label={t("testPages.controls.navigate")} items={navigationLinks} />
          <DropdownLinks label={t("testPages.controls.rightAligned")} items={navigationLinks} align="end" />
        </div>
      </Card>
      <Card>
        <span className="label">{t("testPages.controls.disabledEmptyState")}</span>
        <div className="test-controls-row">
          <DropdownLinks label={t("testPages.controls.availablePages")} items={[
            ...navigationLinks,
            { label: t("testPages.controls.reports"), href: "/reports", description: t("testPages.controls.comingSoon"), disabled: true },
          ]} />
          <DropdownLinks label={t("testPages.controls.disabled")} items={documentationLinks} disabled />
          <DropdownLinks label={t("testPages.controls.emptyMenu")} items={[]} emptyText={t("testPages.controls.noDocs")} />
        </div>
      </Card>
      <Card>
        <span className="label">{t("testPages.controls.textInputs")}</span>
        <TextInput value={plain} placeholder={t("testPages.controls.noLabel")} onChange={setPlain} />
        <TextInput value={model} label={t("testPages.controls.modelName")} placeholder="gpt-4o" onChange={setModel} />
        <TextInput value="locked" label={t("testPages.controls.disabledLabel")} onChange={() => {}} disabled />
      </Card>
      <Card>
        <span className="label">{t("testPages.controls.selectorsLegend")}</span>
        <ItemSelector
          items={sampleItems}
          selectedId={providerId}
          onSelect={setProviderId}
          hasMore={false}
          onLoadMore={() => {}}
          label={t("testPages.controls.provider")}
        />
        <ItemSearcher
          items={sampleItems}
          selectedId={foundId}
          onSelect={setFoundId}
          hasMore={false}
          onLoadMore={() => {}}
          label={t("testPages.controls.findProvider")}
        />
      </Card>
      <Card>
        <span className="label">{t("testPages.controls.registerForm")}</span>
        <form className="test-controls-form" onSubmit={submitForm}>
          <ItemSelector
            items={sampleItems}
            selectedId={formProviderId}
            onSelect={setFormProviderId}
            hasMore={false}
            onLoadMore={() => {}}
            label={t("testPages.controls.provider")}
          />
          <TextInput value={formModel} label={t("testPages.controls.modelName")} placeholder="gpt-4o" onChange={setFormModel} />
          <Button type="submit" disabled={formModel.trim() === ""}>
            {t("testPages.controls.addModel")}
          </Button>
        </form>
        {submitted !== null && <p className="mono">{submitted}</p>}
      </Card>
      <Card>
        <span className="label">{t("testPages.controls.squareButtons")}</span>
        <div className="test-controls-row">
          <Button variant="secondary" square ariaLabel={t("testPages.controls.decrease")} onClick={() => setCount((value) => value - 1)}>
            <MinusIcon />
          </Button>
          <span className="mono" aria-live="polite">{count}</span>
          <Button variant="secondary" square ariaLabel={t("testPages.controls.increase")} onClick={() => setCount((value) => value + 1)}>
            <PlusIcon />
          </Button>
        </div>
      </Card>
      <Card>
        <span className="label">{t("testPages.controls.defaultTemplate", { count: picked.length })}</span>
        <ItemList items={sampleEntries} selectedIds={picked} onSelectionChange={setPicked} />
      </Card>
      <Card>
        <span className="label">{t("testPages.controls.customTemplate")}</span>
        <ItemList
          items={sampleEntries}
          selectedIds={picked}
          onSelectionChange={setPicked}
          renderItem={(item, selected) => (
            <>
              <span className="mono">{item.name}</span>
              <Badge tone={selected ? "success" : "info"}>{selected ? t("testPages.controls.picked") : item.description ?? ""}</Badge>
            </>
          )}
        />
      </Card>
      <Card>
        <span className="label">{t("testPages.controls.singleSelect", { favorite: favorite[0] ?? t("testPages.none") })}</span>
        <ItemList items={sampleEntries} selectedIds={favorite} onSelectionChange={setFavorite} mode="single" />
      </Card>
      <Card>
        <span className="label">{t("testPages.controls.modalDemo")}</span>
        <Button onClick={() => setModalOpen(true)}>
          {t("testPages.controls.openModal")}
        </Button>
        <Modal open={modalOpen} label={t("testPages.controls.demoModal")} title={t("testPages.controls.demoModal")} onClose={() => setModalOpen(false)}>
          <p className="mono">gpt-4o / OpenAI flagship</p>
          <Button variant="secondary" onClick={() => setModalOpen(false)}>
            {t("testPages.controls.dismiss")}
          </Button>
        </Modal>
      </Card>
      <DrawerExamples />
    </section>
  )
}
