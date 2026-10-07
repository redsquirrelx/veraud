import { Card } from "../../shared/ui-kit/index.ts"
import { TASK_KIND_OPTIONS, useTaskVisibility } from "../../shared/task-manager/index.ts"
import "./SettingsPage.css"

export function SettingsPage() {
  const [visibility, update] = useTaskVisibility()

  return (
    <section className="settings-page">
      <div className="home-heading">
        <div>
          <h1>General settings</h1>
        </div>
      </div>
      <Card>
        <span className="label">Task notifications</span>
        <p className="settings-hint">Read-only tasks stay silent unless they fail. Failed tasks always show.</p>
        <div className="settings-tasks">
          {TASK_KIND_OPTIONS.map((option) => (
            <label key={option.kind} className="settings-task">
              <input
                type="checkbox"
                checked={visibility[option.kind] ?? true}
                onChange={(event) => update(option.kind, event.target.checked)}
              />
              <span className="mono">{option.label}</span>
              <span className="label">{option.hint}</span>
            </label>
          ))}
        </div>
      </Card>
    </section>
  )
}
