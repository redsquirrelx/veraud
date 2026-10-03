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
}

export function FilterTabs({ options, value, onChange }: FilterTabsProps) {
  return (
    <div className="ui-filter-tabs" role="tablist">
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          role="tab"
          aria-selected={option.id === value}
          className={option.id === value ? "ui-filter-tab ui-filter-tab-active" : "ui-filter-tab"}
          onClick={() => onChange(option.id)}
        >
          {option.count > 0 ? `${option.label} (${option.count})` : option.label}
        </button>
      ))}
    </div>
  )
}
