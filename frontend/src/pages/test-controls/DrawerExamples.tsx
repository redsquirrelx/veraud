import { useState, type FormEvent } from "react"
import { useTranslation } from "react-i18next"
import { Button, Card, Drawer, TextInput } from "../../shared/ui-kit/index.ts"

type DrawerExample = "basic" | "long" | "form"

export function DrawerExamples() {
  const { t } = useTranslation("common")
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
    setSavedMessage(t("testPages.drawerExamples.savedMessage"))
    close()
  }

  return (
    <>
      <Card>
        <span className="label">{t("testPages.drawerExamples.basic")}</span>
        <p className="label">{t("testPages.drawerExamples.basicHint")}</p>
        <Button onClick={() => setExample("basic")}>{t("testPages.drawerExamples.openBasic")}</Button>
      </Card>
      <Card>
        <span className="label">{t("testPages.drawerExamples.scrollable")}</span>
        <p className="label">{t("testPages.drawerExamples.scrollableHint")}</p>
        <Button onClick={() => setExample("long")}>{t("testPages.drawerExamples.openLong")}</Button>
      </Card>
      <Card>
        <span className="label">{t("testPages.drawerExamples.wideForm")}</span>
        <p className="label">{t("testPages.drawerExamples.wideFormHint")}</p>
        <p className="mono">{t("testPages.drawerExamples.savedName", { name: savedName })}</p>
        <Button onClick={openForm}>{t("testPages.drawerExamples.openForm")}</Button>
        {savedMessage && <p className="label" role="status">{savedMessage}</p>}
      </Card>

      <Drawer open={example === "basic"} title={t("testPages.drawerExamples.basicTitle")} description={t("testPages.drawerExamples.basicDescription")} onClose={close}>
        <div className="test-drawer-content">
          <p>{t("testPages.drawerExamples.basicBody1")}</p>
          <p>{t("testPages.drawerExamples.basicBody2")}</p>
          <Button variant="secondary" onClick={close}>{t("testPages.controls.dismiss")}</Button>
        </div>
      </Drawer>
      <Drawer
        open={example === "long"}
        title={t("testPages.drawerExamples.scrollableTitle")}
        description={t("testPages.drawerExamples.scrollableDescription")}
        onClose={close}
        footer={<Button onClick={close}>{t("testPages.drawerExamples.done")}</Button>}
      >
        <div className="test-drawer-content">
          {Array.from({ length: 12 }, (_, index) => (
            <section className="test-drawer-section" key={index}>
              <h3>{t("testPages.drawerExamples.sectionTitle", { index: index + 1 })}</h3>
              <p>{t("testPages.drawerExamples.sectionBody1")}</p>
              <p>{t("testPages.drawerExamples.sectionBody2")}</p>
            </section>
          ))}
        </div>
      </Drawer>
      <Drawer
        open={example === "form"}
        title={t("testPages.drawerExamples.formTitle")}
        description={t("testPages.drawerExamples.formDescription")}
        size="wide"
        closeOnOverlay={false}
        onClose={close}
        footer={<>
          <Button variant="secondary" onClick={close}>{t("testPages.drawerExamples.cancel")}</Button>
          <Button disabled={!draftName.trim()} onClick={() => saveForm()}>{t("testPages.drawerExamples.saveChanges")}</Button>
        </>}
      >
        <form className="test-drawer-content" onSubmit={saveForm}>
          <TextInput label={t("testPages.drawerExamples.agentName")} value={draftName} onChange={setDraftName} placeholder={t("testPages.drawerExamples.agentNamePlaceholder")} />
          <p className="label">{t("testPages.drawerExamples.formHint")}</p>
        </form>
      </Drawer>
    </>
  )
}
