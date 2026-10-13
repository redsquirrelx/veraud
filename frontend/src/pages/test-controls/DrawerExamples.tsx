import { useState, type FormEvent } from "react"
import { Button, Card, Drawer, TextInput } from "../../shared/ui-kit/index.ts"

type DrawerExample = "basic" | "long" | "form"

export function DrawerExamples() {
  const [example, setExample] = useState<DrawerExample | null>(null)
  const [savedName, setSavedName] = useState("Demo agent")
  const [draftName, setDraftName] = useState(savedName)
  const [savedMessage, setSavedMessage] = useState("")
  const close = () => setExample(null)

  function openForm() {
    setDraftName(savedName)
    setExample("form")
  }

  function saveForm(event?: FormEvent) {
    event?.preventDefault()
    if (!draftName.trim()) return
    setSavedName(draftName.trim())
    setSavedMessage("Saved locally for this playground session. No API request was made.")
    close()
  }

  return (
    <>
      <Card>
        <span className="label">Drawer ┬╖ basic panel</span>
        <p className="label">Slides from the right. Close with Escape, the cross or a click on the backdrop.</p>
        <Button onClick={() => setExample("basic")}>Open basic drawer</Button>
      </Card>
      <Card>
        <span className="label">Drawer ┬╖ scrollable content with fixed actions</span>
        <p className="label">The header and footer remain visible while the content scrolls.</p>
        <Button onClick={() => setExample("long")}>Open long-content drawer</Button>
      </Card>
      <Card>
        <span className="label">Drawer ┬╖ wide form with local save and cancel</span>
        <p className="label">Backdrop closing is disabled in this example. Cancel discards edits; reopening loads the last saved name.</p>
        <p className="mono">Saved name: {savedName}</p>
        <Button onClick={openForm}>Open form drawer</Button>
        {savedMessage && <p className="label" role="status">{savedMessage}</p>}
      </Card>

      <Drawer open={example === "basic"} title="Basic drawer" description="A reusable side panel for details and configuration." onClose={close}>
        <div className="test-drawer-content">
          <p>This content is rendered above the page. The background cannot be interacted with until the drawer closes.</p>
          <p>Keyboard focus stays inside the drawer and returns to its opening button when you close it.</p>
          <Button variant="secondary" onClick={close}>Dismiss</Button>
        </div>
      </Drawer>
      <Drawer
        open={example === "long"}
        title="Scrollable drawer"
        description="Independent content scrolling with a persistent header and footer."
        onClose={close}
        footer={<Button onClick={close}>Done</Button>}
      >
        <div className="test-drawer-content">
          {Array.from({ length: 12 }, (_, index) => (
            <section className="test-drawer-section" key={index}>
              <h3>Configuration section {index + 1}</h3>
              <p>Example content for an agent setting, including its purpose, available values and explanatory details.</p>
              <p>Scroll through the sections to check that the actions remain accessible at the bottom of the drawer.</p>
            </section>
          ))}
        </div>
      </Drawer>
      <Drawer
        open={example === "form"}
        title="Demo agent configuration"
        description="A wide drawer with editable demonstration data."
        size="wide"
        closeOnOverlay={false}
        onClose={close}
        footer={<>
          <Button variant="secondary" onClick={close}>Cancel</Button>
          <Button disabled={!draftName.trim()} onClick={() => saveForm()}>Save changes</Button>
        </>}
      >
        <form className="test-drawer-content" onSubmit={saveForm}>
          <TextInput label="Agent name" value={draftName} onChange={setDraftName} placeholder="Enter an agent name..." />
          <p className="label">This form demonstrates layout and local state only. It does not configure a real agent.</p>
        </form>
      </Drawer>
    </>
  )
}
