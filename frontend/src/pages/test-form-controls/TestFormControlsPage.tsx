import { useState } from "react"
import { Link } from "react-router-dom"
import { Card, Checkbox, Combobox, RadioButton, Switch } from "../../shared/ui-kit/index.ts"
import "./TestFormControlsPage.css"

const providers = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google", label: "Google" },
  { value: "unavailable", label: "Unavailable provider", disabled: true },
]

export function TestFormControlsPage() {
  const [checked, setChecked] = useState(false)
  const [mixed, setMixed] = useState(true)
  const [mixedChecked, setMixedChecked] = useState(false)
  const [provider, setProvider] = useState("")
  const [protocol, setProtocol] = useState("https")
  const [notifications, setNotifications] = useState(true)
  const [invalidChecked, setInvalidChecked] = useState(false)
  const [invalidProvider, setInvalidProvider] = useState("")
  const [invalidRadio, setInvalidRadio] = useState("")
  const [invalidSwitch, setInvalidSwitch] = useState(false)

  return (
    <section className="page form-controls-page">
      <Link to="/test">ΓåÉ All playgrounds</Link>
      <h1>Form controls</h1>
      <p className="form-controls-intro">Interactive, selected, indeterminate, disabled, and validation states. Use Tab to focus, Space to toggle, and arrow keys to navigate options.</p>
      <div className="form-controls-grid">
        <Card>
          <h2>Checkboxes</h2>
          <Checkbox label="Include dependencies" checked={checked} onChange={setChecked} description="Click or press Space to toggle." />
          <Checkbox label="Select all files" checked={mixedChecked} indeterminate={mixed} onChange={(value) => { setMixed(false); setMixedChecked(value) }} description="Starts in an indeterminate state." />
          <Checkbox label="Disabled unchecked" checked={false} disabled onChange={() => {}} />
          <Checkbox label="Disabled checked" checked disabled onChange={() => {}} />
          <Checkbox label="Accept the terms" checked={invalidChecked} onChange={setInvalidChecked} error={invalidChecked ? undefined : "Please accept the terms to continue."} />
        </Card>
        <Card>
          <h2>Comboboxes</h2>
          <Combobox label="AI provider" value={provider} options={providers} onChange={setProvider} description="Arrow keys, Home/End, Enter, Escape, and type-ahead are supported." />
          <Combobox label="Disabled empty" value="" options={providers} disabled onChange={() => {}} />
          <Combobox label="Disabled selected" value="openai" options={providers} disabled onChange={() => {}} />
          <Combobox label="Required provider" value={invalidProvider} options={providers} onChange={setInvalidProvider} error={invalidProvider ? undefined : "Select a provider to continue."} />
          <Combobox label="No available options" value="" options={[]} onChange={() => {}} />
        </Card>
        <Card>
          <h2>Radio buttons</h2>
          <fieldset className="form-controls-group">
            <legend>Clone protocol</legend>
            <RadioButton label="HTTPS" name="playground-protocol" value="https" checked={protocol === "https"} onChange={setProtocol} />
            <RadioButton label="SSH" name="playground-protocol" value="ssh" checked={protocol === "ssh"} onChange={setProtocol} description="Uses your existing SSH configuration." />
          </fieldset>
          <RadioButton label="Disabled unselected" name="disabled-off" value="off" checked={false} disabled onChange={() => {}} />
          <RadioButton label="Disabled selected" name="disabled-on" value="on" checked disabled onChange={() => {}} />
          <fieldset className="form-controls-group">
            <legend>Required choice</legend>
            <RadioButton label="Manual review" name="review" value="manual" checked={invalidRadio === "manual"} onChange={setInvalidRadio} error={invalidRadio ? undefined : "Choose a review mode."} />
            <RadioButton label="Automatic review" name="review" value="auto" checked={invalidRadio === "auto"} onChange={setInvalidRadio} />
          </fieldset>
        </Card>
        <Card>
          <h2>Switches</h2>
          <Switch label="Task notifications" checked={notifications} onChange={setNotifications} description="Enable or disable notifications." />
          <Switch label="Disabled off" checked={false} disabled onChange={() => {}} />
          <Switch label="Disabled on" checked disabled onChange={() => {}} />
          <Switch label="Enable audit logging" checked={invalidSwitch} onChange={setInvalidSwitch} error={invalidSwitch ? undefined : "Audit logging is required for this example."} />
        </Card>
      </div>
      <Card>
        <h2>Live values</h2>
        <pre className="form-controls-values">{JSON.stringify({ includeDependencies: checked, selectAll: mixed ? "indeterminate" : mixedChecked, provider: provider || null, protocol, notifications }, null, 2)}</pre>
      </Card>
    </section>
  )
}
