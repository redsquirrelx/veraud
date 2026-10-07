import { useState, type FormEvent } from "react"
import { Badge, Button, Card, ItemList, ItemSearcher, ItemSelector, MinusIcon, Modal, PlusIcon, TextInput, type ItemListEntry, type ItemSelectorItem } from "../../shared/ui-kit/index.ts"
import "./TestControlsPage.css"

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

export function TestControlsPage() {
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
      <h1>Controls playground</h1>
      <Card>
        <span className="label">Text inputs with floating legend</span>
        <TextInput value={plain} placeholder="No label here" onChange={setPlain} />
        <TextInput value={model} label="Model name" placeholder="gpt-4o" onChange={setModel} />
        <TextInput value="locked" label="Disabled" onChange={() => {}} disabled />
      </Card>
      <Card>
        <span className="label">Selectors share the same legend</span>
        <ItemSelector
          items={sampleItems}
          selectedId={providerId}
          onSelect={setProviderId}
          hasMore={false}
          onLoadMore={() => {}}
          label="Provider"
        />
        <ItemSearcher
          items={sampleItems}
          selectedId={foundId}
          onSelect={setFoundId}
          hasMore={false}
          onLoadMore={() => {}}
          label="Find a provider"
        />
      </Card>
      <Card>
        <span className="label">Register model form</span>
        <form className="test-controls-form" onSubmit={submitForm}>
          <ItemSelector
            items={sampleItems}
            selectedId={formProviderId}
            onSelect={setFormProviderId}
            hasMore={false}
            onLoadMore={() => {}}
            label="Provider"
          />
          <TextInput value={formModel} label="Model name" placeholder="gpt-4o" onChange={setFormModel} />
          <Button type="submit" disabled={formModel.trim() === ""}>
            Add model
          </Button>
        </form>
        {submitted !== null && <p className="mono">{submitted}</p>}
      </Card>
      <Card>
        <span className="label">Square buttons</span>
        <div className="test-controls-row">
          <Button variant="secondary" square ariaLabel="Decrease" onClick={() => setCount((value) => value - 1)}>
            <MinusIcon />
          </Button>
          <span className="mono" aria-live="polite">{count}</span>
          <Button variant="secondary" square ariaLabel="Increase" onClick={() => setCount((value) => value + 1)}>
            <PlusIcon />
          </Button>
        </div>
      </Card>
      <Card>
        <span className="label">Item list with the default template ({picked.length} selected)</span>
        <ItemList items={sampleEntries} selectedIds={picked} onSelectionChange={setPicked} />
      </Card>
      <Card>
        <span className="label">Item list with a custom template</span>
        <ItemList
          items={sampleEntries}
          selectedIds={picked}
          onSelectionChange={setPicked}
          renderItem={(item, selected) => (
            <>
              <span className="mono">{item.name}</span>
              <Badge tone={selected ? "success" : "info"}>{selected ? "picked" : item.description ?? ""}</Badge>
            </>
          )}
        />
      </Card>
      <Card>
        <span className="label">Single-select list (favorite: {favorite[0] ?? "none"})</span>
        <ItemList items={sampleEntries} selectedIds={favorite} onSelectionChange={setFavorite} mode="single" />
      </Card>
      <Card>
        <span className="label">Modal demo</span>
        <Button onClick={() => setModalOpen(true)}>
          Open modal
        </Button>
        <Modal open={modalOpen} label="Demo modal" title="Demo modal" onClose={() => setModalOpen(false)}>
          <p className="mono">gpt-4o / OpenAI flagship</p>
          <Button variant="secondary" onClick={() => setModalOpen(false)}>
            Dismiss
          </Button>
        </Modal>
      </Card>
    </section>
  )
}
