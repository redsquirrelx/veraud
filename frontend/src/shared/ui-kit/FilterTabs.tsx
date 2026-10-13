import "./FilterTabs.css"

export interface FilterOption {
  id: string
  label: string
  count: number
}

interface FilterTabsProps {
  options: FilterOption[]
  value: string
  onChange: (id: string) => void
  label?: string
}

export function FilterTabs({ options, value, onChange, label }: FilterTabsProps) {
  return (
    <div className="ui-filter-tabs" role="tablist" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          role="tab"
          aria-selected={option.id === value}
          tabIndex={option.id === value ? 0 : -1}
          onKeyDown={(event) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
            event.preventDefault()
            const index = options.findIndex((item) => item.id === option.id)
            const next = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1
              : (index + (event.key === "ArrowRight" ? 1 : -1) + options.length) % options.length
            onChange(options[next].id)
            event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role=tab]")[next]?.focus()
          }}
          className={option.id === value ? "ui-filter-tab ui-filter-tab-active" : "ui-filter-tab"}
          onClick={() => onChange(option.id)}
        >
          {option.count > 0 ? `${option.label} (${option.count})` : option.label}
        </button>
      ))}
    </div>
  )
}
