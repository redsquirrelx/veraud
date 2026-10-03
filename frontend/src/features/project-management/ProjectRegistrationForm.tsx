import { Button, TextInput } from "../../shared/ui-kit/index.ts"
import type { useRegisterProject } from "./useRegisterProject.ts"
import "./ProjectRegistrationForm.css"

type Registration = ReturnType<typeof useRegisterProject>

export function ProjectRegistrationForm({ registration }: { registration: Registration }) {
  const canSubmit = registration.url.trim() !== "" && !registration.cooling

  return (
    <div className="registration-form">
      <TextInput
        value={registration.url}
        placeholder="https://github.com/owner/repo"
        onChange={registration.changeUrl}
      />
      <Button loading={registration.cooling} loadingText="Wait" disabled={!canSubmit} onClick={() => void registration.register()}>
        Register project
      </Button>
    </div>
  )
}
