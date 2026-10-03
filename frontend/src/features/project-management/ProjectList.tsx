import { FilterTabs, Pagination, RefreshButton, SortButton, TextInput, type FilterOption } from "../../shared/ui-kit/index.ts"
import { ProjectCard } from "./ProjectCard.tsx"
import { type ProjectSortMode, type ProjectStatusFilter, type useProjects } from "./useProjects.ts"
import "./ProjectList.css"

const sortOptions: Array<FilterOption & { id: ProjectSortMode }> = [
  { id: "title", label: "Title", count: 0 },
  { id: "date", label: "Date", count: 0 },
]

const statusOptions: Array<FilterOption & { id: ProjectStatusFilter }> = [
  { id: "ALL", label: "All", count: 0 },
  { id: "QUEUED", label: "Queued", count: 0 },
  { id: "READY", label: "Ready", count: 0 },
  { id: "SYNCING", label: "Syncing", count: 0 },
]

export function ProjectList({ listing }: { listing: ReturnType<typeof useProjects> }) {
  const { projects, total, countFor, search, setSearch, status, setStatus, sortMode, setSortMode, azDirection, toggleAzDirection, page, pageCount, setPage, loading, loadError, refresh } = listing

  const options = statusOptions.map((option) => ({ ...option, count: countFor(option.id) }))

  return (
    <section aria-label="Projects">
      <p className="label">
        {total} registered project{total === 1 ? "" : "s"}
      </p>
      <div className="project-list-bar">
        <TextInput value={search} placeholder="Search by repository" onChange={setSearch} />
        <FilterTabs options={options} value={status} onChange={(id) => setStatus(id as ProjectStatusFilter)} />
        <FilterTabs options={sortOptions} value={sortMode} onChange={(id) => setSortMode(id as ProjectSortMode)} />
        <SortButton direction={azDirection} onToggle={toggleAzDirection} />
        <RefreshButton loading={loading} onClick={() => void refresh()} />
      </div>
      {loadError ? (
        <p className="project-list-note">Could not load projects</p>
      ) : loading && projects.length === 0 ? (
        <div className="project-list" aria-label="Loading projects">
          <div className="project-skeleton" />
          <div className="project-skeleton" />
          <div className="project-skeleton" />
        </div>
      ) : projects.length === 0 ? (
        <p className="project-list-note">No projects yet</p>
      ) : (
        <>
          <div className="project-list">
            {projects.map((project) => (
              <ProjectCard key={project.id} project={project} />
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
