import { Link } from "react-router-dom"
import { ArrowRightIcon } from "../../shared/ui-kit/index.ts"
import "./TestIndexPage.css"

const testPages = [
  { path: "/test/components", title: "Components", description: "Explore the UI kit and combined component examples." },
  { path: "/test/selector", title: "Selectors", description: "Review item selection and search controls." },
  { path: "/test/dropdown", title: "Dropdowns", description: "Review action menus with selectable options." },
  { path: "/test/stage-showcase", title: "Stage showcase", description: "Review the compact stage views with realistic payloads." },
  { path: "/test/controls", title: "Controls", description: "Review interactive controls and their states." },
  { path: "/test/form-controls", title: "Form controls", description: "Explore checkboxes, comboboxes, radio buttons, and switches." },
  { path: "/test/directory", title: "Directory", description: "Explore directory trees and file navigation." },
  { path: "/test/file-viewer", title: "File viewer", description: "Review file previews and code rendering." },
  { path: "/test_sidebar", title: "Sidebar", description: "Review sidebar navigation and layouts." },
]

export function TestIndexPage() {
  return (
    <section className="page test-index-page">
      <h1>Test playgrounds</h1>
      <p className="label">Choose a playground to review its components and interactions.</p>
      <nav className="test-index-links" aria-label="Test playgrounds">
        {testPages.map((page) => (
          <Link key={page.path} to={page.path} className="test-index-link">
            <span className="test-index-info">
              <span className="mono">{page.title}</span>
              <span className="label">{page.description}</span>
            </span>
            <ArrowRightIcon />
          </Link>
        ))}
      </nav>
    </section>
  )
}
