import { useState } from "react"
import { Link } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Card, Checkbox, Combobox, RadioButton, Switch } from "../../shared/ui-kit/index.ts"
import "./TestFormControlsPage.css"

const providers = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google", label: "Google" },
  { value: "unavailable", labelKey: "testPages.formControls.unavailableProvider", disabled: true },
] as const

export function TestFormControlsPage() {
  const { t } = useTranslation("common")
  const providerOptions = providers.map((provider) => ({
    value: provider.value,
    label: "labelKey" in provider ? t(provider.labelKey) : provider.label,
    disabled: "disabled" in provider ? provider.disabled : undefined,
  }))
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
      <Link to="/test">{t("testPages.formControls.back", { label: t("testPages.allPlaygrounds") })}</Link>
      <h1>{t("testPages.formControls.title")}</h1>
      <p className="form-controls-intro">{t("testPages.formControls.intro")}</p>
      <div className="form-controls-grid">
        <Card>
          <h2>{t("testPages.formControls.checkboxes")}</h2>
          <Checkbox label={t("testPages.formControls.includeDeps")} checked={checked} onChange={setChecked} description={t("testPages.formControls.includeDepsHint")} />
          <Checkbox label={t("testPages.formControls.selectAll")} checked={mixedChecked} indeterminate={mixed} onChange={(value) => { setMixed(false); setMixedChecked(value) }} description={t("testPages.formControls.selectAllHint")} />
          <Checkbox label={t("testPages.formControls.disabledUnchecked")} checked={false} disabled onChange={() => {}} />
          <Checkbox label={t("testPages.formControls.disabledChecked")} checked disabled onChange={() => {}} />
          <Checkbox label={t("testPages.formControls.acceptTerms")} checked={invalidChecked} onChange={setInvalidChecked} error={invalidChecked ? undefined : t("testPages.formControls.acceptTermsError")} />
        </Card>
        <Card>
          <h2>{t("testPages.formControls.comboboxes")}</h2>
          <Combobox label={t("testPages.formControls.aiProvider")} value={provider} options={providerOptions} onChange={setProvider} description={t("testPages.formControls.comboboxHint")} />
          <Combobox label={t("testPages.formControls.disabledEmpty")} value="" options={providerOptions} disabled onChange={() => {}} />
          <Combobox label={t("testPages.formControls.disabledSelected")} value="openai" options={providerOptions} disabled onChange={() => {}} />
          <Combobox label={t("testPages.formControls.requiredProvider")} value={invalidProvider} options={providerOptions} onChange={setInvalidProvider} error={invalidProvider ? undefined : t("testPages.formControls.requiredProviderError")} />
          <Combobox label={t("testPages.formControls.noAvailableOptions")} value="" options={[]} onChange={() => {}} />
        </Card>
        <Card>
          <h2>{t("testPages.formControls.radios")}</h2>
          <fieldset className="form-controls-group">
            <legend>{t("testPages.formControls.cloneProtocol")}</legend>
            <RadioButton label="HTTPS" name="playground-protocol" value="https" checked={protocol === "https"} onChange={setProtocol} />
            <RadioButton label="SSH" name="playground-protocol" value="ssh" checked={protocol === "ssh"} onChange={setProtocol} description={t("testPages.formControls.sshHint")} />
          </fieldset>
          <RadioButton label={t("testPages.formControls.disabledUnselected")} name="disabled-off" value="off" checked={false} disabled onChange={() => {}} />
          <RadioButton label={t("testPages.formControls.disabledSelected")} name="disabled-on" value="on" checked disabled onChange={() => {}} />
          <fieldset className="form-controls-group">
            <legend>{t("testPages.formControls.requiredChoice")}</legend>
            <RadioButton label={t("testPages.formControls.manualReview")} name="review" value="manual" checked={invalidRadio === "manual"} onChange={setInvalidRadio} error={invalidRadio ? undefined : t("testPages.formControls.reviewModeError")} />
            <RadioButton label={t("testPages.formControls.automaticReview")} name="review" value="auto" checked={invalidRadio === "auto"} onChange={setInvalidRadio} />
          </fieldset>
        </Card>
        <Card>
          <h2>{t("testPages.formControls.switches")}</h2>
          <Switch label={t("testPages.formControls.taskNotifications")} checked={notifications} onChange={setNotifications} description={t("testPages.formControls.notificationsHint")} />
          <Switch label={t("testPages.formControls.disabledOff")} checked={false} disabled onChange={() => {}} />
          <Switch label={t("testPages.formControls.disabledOn")} checked disabled onChange={() => {}} />
          <Switch label={t("testPages.formControls.enableAudit")} checked={invalidSwitch} onChange={setInvalidSwitch} error={invalidSwitch ? undefined : t("testPages.formControls.auditRequiredError")} />
        </Card>
      </div>
      <Card>
        <h2>{t("testPages.formControls.liveValues")}</h2>
        <pre className="form-controls-values">{JSON.stringify({ includeDependencies: checked, selectAll: mixed ? "indeterminate" : mixedChecked, provider: provider || null, protocol, notifications }, null, 2)}</pre>
      </Card>
    </section>
  )
}
