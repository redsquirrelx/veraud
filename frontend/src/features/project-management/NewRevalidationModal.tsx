import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { Button, ItemSelector, Modal } from "../../shared/ui-kit/index.ts"
import "./NewRevalidationModal.css"

// Mock target commits only; no repository requests or revalidation execution.
const targetCommits = [
  { hash: "b37d4e18a26c590f73b1a8046e92c5d0a7f138bc", subject: "Fix remaining validation issues" },
  { hash: "d62a9f340b8e715c4a906d2f83e1b57a09c624ed", subject: "Add regression coverage" },
  { hash: "f09c7b256e1a348d9c2b064f85a7d13e60b492ac", subject: "Refine error handling" },
]

export function NewRevalidationModal({ commitHash, revisionName, onClose }: {
  commitHash: string, revisionName: string, onClose: () => void,
}) {
  const { i18n } = useTranslation("projects")
  const spanish = i18n.resolvedLanguage?.startsWith("es")
  const labels = spanish ? {
    title: "Nueva revalidación", description: "Verifica los hallazgos pendientes contra un commit más reciente.",
    last: "Último commit evaluado", target: "Seleccionar commit de destino", placeholder: "Selecciona un commit más reciente…",
    start: "Iniciar revalidación", sample: "Datos de ejemplo", notice: "Solo es una maqueta. No se ha iniciado ninguna revalidación.",
  } : {
    title: "New revalidation", description: "Verify remaining findings against a newer commit.",
    last: "Last evaluated commit", target: "Select target commit", placeholder: "Select a newer commit…",
    start: "Start revalidation", sample: "Sample data", notice: "This is a mockup. No revalidation has been started.",
  }
  const form = useRef<HTMLFormElement>(null)
  const [target, setTarget] = useState("")
  const [submitted, setSubmitted] = useState(false)

  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null
    form.current?.querySelector<HTMLButtonElement>(".ui-item-button")?.focus()
    return () => { trigger?.focus() }
  }, [])

  return <Modal open label={labels.title} title={labels.title} onClose={onClose}>
    <form ref={form} className="new-revalidation-form" onSubmit={(event) => { event.preventDefault(); if (target) setSubmitted(true) }}>
      <p className="new-revalidation-description">{labels.description}</p>
      <div className="ui-field">
        <span className="ui-field-label">{labels.last}</span>
        <div className="new-revalidation-commit">
          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M2 10h5m6 0h5" /><circle cx="10" cy="10" r="3" />
          </svg>
          <code title={commitHash}>{commitHash.slice(0, 7)}</code>
          <span>{revisionName}</span>
        </div>
      </div>
      <ItemSelector
        label={labels.target}
        placeholder={labels.placeholder}
        items={targetCommits.filter((commit) => commit.hash !== commitHash).map((commit) => ({
          id: commit.hash, label: commit.hash.slice(0, 7), detail: commit.subject,
        }))}
        selectedId={target || null}
        onSelect={(id) => { setTarget(id); setSubmitted(false) }}
        hasMore={false}
        onLoadMore={() => {}}
      />
      {submitted && <p className="new-revalidation-notice" role="status">{labels.notice}</p>}
      <div className="new-revalidation-footer">
        <span className="label">{labels.sample}</span>
        <Button type="submit" variant="primary" disabled={!target}>{labels.start}</Button>
      </div>
    </form>
  </Modal>
}
