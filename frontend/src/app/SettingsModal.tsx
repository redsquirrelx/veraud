import { useTranslation } from "react-i18next"
import { Modal } from "../shared/ui-kit/Modal.tsx"
import { SettingsPage, type SettingsTab } from "../pages/settings/SettingsPage.tsx"
import "./SettingsModal.css"

export function SettingsModal({ open, onClose, initialTab }: { open: boolean; onClose: () => void; initialTab?: SettingsTab }) {
  const { t } = useTranslation("common")
  return (
    <Modal
      open={open}
      label={t("navigation.settings")}
      title={t("navigation.settings")}
      closeOnBackdrop={false}
      closeOnEscape={false}
      onClose={onClose}
      size="default"
    >
      <div className="app-settings-modal-content">
        {open && <SettingsPage initialTab={initialTab} />}
      </div>
    </Modal>
  )
}
