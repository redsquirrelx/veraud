# Frontend i18n Conventions

## 1. Languages

- Supported language identifiers: `es` and `en`.
- Use neutral Spanish with consistent terminology.
- Use English as the fallback language.
- Normalize variants such as `es-CL` and `en-US` to `es` and `en`.
- Display native language names in the selector: **Español** and **English**.
- Resolve the language in this order: saved preference, supported browser language, English.

## 2. Resource Organization

Store resources in `frontend/src/shared/i18n/locales/{language}/{namespace}.json`.

| Namespace | Content |
| --- | --- |
| `common` | Reusable actions, navigation, and shared controls |
| `projects` | Project registration, listing, versions, and analysis |
| `settings` | Preferences, models, and credentials |
| `agents` | Agent configuration, executions, and monitoring |
| `tasks` | Task types, statuses, and task menu |

Assign each string to the domain it represents, regardless of the screen where it appears. Reserve `common` for genuinely shared concepts.

## 3. Keys

- Write keys in English, using `camelCase` segments.
- Use a stable, semantic hierarchy that is independent of the displayed text.
- Specify the namespace explicitly in translation calls.
- Use separate keys for different purposes, even when their initial text is identical.

```tsx
t("common:actions.save")
t("projects:registration.submit")
t("settings:preferences.language")
t("agents:execution.status.running")
```

Example English resource:

```json
{
  "registration": {
    "title": "Register project",
    "submit": "Register project",
    "success": "Project {{name}} was registered successfully."
  }
}
```

## 4. Sentences and Interpolation

- Translate complete sentences or labels.
- Pass dynamic values as parameters with descriptive names.
- Avoid concatenating fragments to build sentences.

```tsx
t("projects:registration.success", { name: project.name })
```

Each language can change the order of parameters within a sentence.

## 5. Plurals

Use i18next pluralization rules and the reserved `count` parameter.

```json
{
  "selectedCount_one": "{{count}} project selected",
  "selectedCount_other": "{{count}} projects selected"
}
```

```tsx
t("projects:selectedCount", { count: selectedProjects.length })
```

Add a `_zero` variant when the zero case requires a specific message.

## 6. Identifiers and Labels

- Keep internal identifiers independent of the language.
- Translate labels at render time so they respond to language changes.
- Apply this rule to tabs, statuses, task types, and options.
- Keep routes, persisted values, and API contracts stable.

```tsx
const tabs = [
  { id: "agents", labelKey: "settings:tabs.agents" },
  { id: "preferences", labelKey: "settings:tabs.preferences" },
] as const

// When rendering the label:
t(tab.labelKey)
```

## 7. Translation Scope

Translate:

- Titles, buttons, navigation, and forms.
- Placeholders, tooltips, and accessibility labels.
- Empty states, validation messages, notifications, and frontend-owned errors.
- Labels corresponding to statuses or codes received from the API.

Preserve as content:

- User-entered names.
- Provider and model names.
- File paths, code, and symbol names.
- Agent-generated results and original technical details.

For example, display the `running` status as “En ejecución” in Spanish while retaining its internal identifier.

## 8. Style and Glossary

- Use sentence case: “Register project”.
- Use action verbs for buttons: Save, Cancel, Delete. In Spanish, use infinitives: Guardar, Cancelar, Eliminar.
- Do not add trailing periods to labels or titles.
- Write messages as complete sentences with punctuation.

| English | Spanish |
| --- | --- |
| Settings | Configuración |
| Preferences | Preferencias |
| Project | Proyecto |
| Agent | Agente |
| Task | Tarea |
| Execution | Ejecución |
| Credential | Credencial |
| Token | Token |
| Branch | Rama |
| Commit | Commit |

## 9. Formatting

- Format dates, numbers, and percentages according to the selected language.
- Use `Intl` through shared utilities.
- Preserve the original representation of data and API contracts.
- Format percentages with the appropriate separators and spacing.
- Separate value formatting from sentence translation.

```tsx
t("projects:details.registeredAt", {
  date: formatDate(project.registeredAt),
})
```

## 10. Consistency and Verification

- Maintain matching keys across both languages, accounting for applicable plural variants.
- Type-check translation keys in code with TypeScript.
- Include a resource parity check.
- Treat missing translations as defects, even when English fallback is available.
- Set the language explicitly in tests to avoid dependence on the environment.

## 11. Formatting Utilities

- Never call `toLocaleString`, `toLocaleDateString`, or `new Intl.*(undefined, …)`: the implicit browser locale ignores the selected language.
- Use the shared helpers in `frontend/src/shared/i18n/format.ts`: `formatNumber`, `formatDate`, `formatDateTime`, and `getLocale`.
- Call them during render, never at module scope: a module-level `Intl` instance freezes the locale of the first render.
- Components pick up the new locale automatically because they re-render through react-i18next (`useTranslation` / `useLanguage`).
- Keep raw values for inputs, API payloads, and persisted data; format only for display.

```tsx
import { formatDate, formatNumber } from "../../shared/i18n/format.ts"

t("projects:details.registeredAt", { date: formatDate(project.registeredAt) })
formatNumber(budget)
```

## 12. Dynamic Messages and Errors

- Translate at render time. When a message must follow language changes, store its key (plus interpolation values) in state, not the finished English string.

```tsx
const [errorKey, setErrorKey] = useState<"agents:errors.saveFailed" | null>(null)
// ...
{errorKey && <p role="alert">{t(errorKey)}</p>}
```

- For API failures without stable codes, show a translated generic message and keep the technical detail (backend message) alongside it; never drop the detail.
- When the backend provides stable error codes, map each code to a translation key; unknown codes fall back to the generic message.
- Labels defined outside components (option lists, status maps) must use the identifier-plus-`labelKey` pattern from section 6 so they translate at render time.

## Step 1 Outcome

These rules and the glossary form the agreement before implementation. Subsequent steps turn them into configuration, translation resources, and code.
