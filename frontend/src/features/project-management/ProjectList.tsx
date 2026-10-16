import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { FilterTabs, Pagination, RefreshButton, SortButton, TextInput, type FilterOption } from "../../shared/ui-kit/index.ts"
import { ProjectCard } from "./ProjectCard.tsx"
import { type ProjectSortMode, type ProjectStatusFilter, type useProjects } from "./useProjects.ts"
import "./ProjectList.css"

const sortOptions: Array<{ id: ProjectSortMode, labelKey: ParseKeys<"projects"> }> = [
  { id: "title", labelKey: "list.sort.title" },
  { id: "date", labelKey: "list.sort.date" },
]

const statusOptions: Array<{ id: ProjectStatusFilter, labelKey: ParseKeys<"projects"> }> = [
  { id: "ALL", labelKey: "status.projectFilter.all" },
  { id: "QUEUED", labelKey: "status.projectFilter.queued" },
  { id: "READY", labelKey: "status.projectFilter.ready" },
  { id: "SYNCING", labelKey: "status.projectFilter.syncing" },
]

export function ProjectList({ listing }: { listing: ReturnType<typeof useProjects> }) {
  const { t } = useTranslation("projects")
  const { projects, total, countFor, search, setSearch, status, setStatus, sortMode, setSortMode, azDirection, toggleAzDirection, pinned, togglePin, page, pageCount, setPage, loading, loadError, refresh } = listing

  const filterOptions: FilterOption[] = statusOptions.map((option) => ({ id: option.id, label: t(option.labelKey), count: countFor(option.id) }))
  const sortTabs: FilterOption[] = sortOptions.map((option) => ({ id: option.id, label: t(option.labelKey), count: 0 }))

  return (
    <section aria-label={t("list.sectionLabel")}>
      <p className="label">
        {t("list.registeredCount", { count: total })}
      </p>
      <div className="project-list-bar">
        <TextInput value={search} placeholder={t("list.searchPlaceholder")} onChange={setSearch} />
        <FilterTabs options={filterOptions} value={status} onChange={(id) => setStatus(id as ProjectStatusFilter)} />
        <FilterTabs options={sortTabs} value={sortMode} onChange={(id) => setSortMode(id as ProjectSortMode)} />
        <SortButton direction={azDirection} onToggle={toggleAzDirection} />
        <RefreshButton loading={loading} onClick={() => void refresh()} />
      </div>
      {loadError ? (
        <p className="project-list-note">{t("list.loadError")}</p>
      ) : loading && projects.length === 0 ? (
        <div className="project-list" aria-label={t("list.loadingLabel")}>
          <div className="project-skeleton" />
          <div className="project-skeleton" />
          <div className="project-skeleton" />
        </div>
      ) : projects.length === 0 ? (
        <p className="project-list-note">{t("list.empty")}</p>
      ) : (
        <>
          <div className="project-list">
            {projects.map((project) => (
              <ProjectCard key={project.id} project={project} pinned={pinned.includes(project.id)} onTogglePin={togglePin} />
            ))}
          </div>
          <div className="pagination-block">
            <Pagination page={page} pageCount={pageCount} onChange={setPage} />
          </div>
        </>
      )}
    </section>
  )
}
