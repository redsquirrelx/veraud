# Frontend Contract — ItemList

Dumb, reusable selectable list. It iterates entries and owns
single/multi selection; it never defines the row look: the caller
injects it through `renderItem`, defaulting to `ItemListItem` (name
plus optional description). No fetching, no persistence: the caller
owns `items` and `selectedIds` and receives the next selection.

Source of truth: `frontend/src/shared/ui-kit/ItemList.tsx`
(render), `ItemList.css` (styling contract). Playgrounds:
`/test/controls` (default template, custom template, single mode),
`/settings` (real templates).

## Import

```tsx
import { ItemList, ItemListItem, type ItemListEntry } from "../../shared/ui-kit/index.ts"
```

## Props

| Prop | Type | Default | Meaning |
|---|---|---|---|
| `items` | `ItemListEntry[]` | required | `{ id: string, name: string, description?: string }`. Order is caller-owned. |
| `selectedIds` | `string[]` | required | Currently selected ids. The list only reads them. |
| `onSelectionChange` | `(ids: string[]) => void` | required | Next selection after a pick. `multiple` toggles one id; `single` reports `[id]` (or `[]` when re-picking the selected one), so single-select is enforced inside, not by the caller. |
| `mode` | `"single" \| "multiple"` | `"multiple"` | Selection rule, mirrored in `aria-multiselectable`. |
| `loading` | `boolean` | `false` | With no items yet, renders three shimmer skeleton rows instead of the empty text. |
| `renderItem` | `(item, selected) => ReactNode` | `ItemListItem` | Row template. Receives the entry and its selected flag, so custom templates can react (badges, previews, remove buttons). |
| `emptyText` | `string` | `"No items yet"` | Placeholder when there is nothing to show and it is not loading. |

## Example

```tsx
<ItemList
  items={models.map((model) => ({ id: String(model.id), name: model.name }))}
  selectedIds={modelId}
  onSelectionChange={setModelId}
  mode="single"
  loading={loading}
  emptyText="No models registered yet"
  renderItem={(entry) => {
    const model = models.find((candidate) => String(candidate.id) === entry.id)
    if (model === undefined) {
      return null
    }
    return <ModelListItem name={model.name} provider={model.provider} inUse={model.inUse} onRemove={() => void deleteModel(model)} />
  }}
/>
```

## Behaviour

- **Picking**: click, `Enter` or `Space` on a row reports the next
  selection. Rows are `div[role="option"]` with `tabIndex={0}`
  (not buttons) precisely so templates may contain their own buttons:
  an inner action stops propagation and never toggles the row.
- **Loading**: skeleton rows are `aria-hidden` inside an
  `aria-busy` list; they show only while `items` is still empty, so
  refreshes with data never flash.
- **Entrance**: rows animate in once (`160ms` fade plus rise),
  matching the selector panels. Stable keys mean refreshes do not
  re-animate existing rows.
- **Fixed frame**: the list is always `240px` tall with its own
  scroll, so side-by-side lists stay aligned. Rows are separated by
  `1px` dividers (`#cbd5e1`); selection is an inset ring plus border
  colour, which no scroll container can clip.

## Styling contract

Classes the component relies on: `ui-item-list-rows`
(container), `ui-item-list-row` plus `ui-item-list-active`,
`ui-item-list-skeleton`, with first/last row radius fixups. Font is
`12px`; dividers and frame are documented above.

## Accessibility

`listbox` with `aria-label="Items"`, options expose
`aria-selected`, focus is visible (`outline-offset: -2px`). Colour
is never the only signal: selection also changes the border, and
templates are expected to add text (badges, labels).

Out of scope: fetching, pagination, drag reorder, keyboard
type-ahead (that is `ItemSearcher`).
