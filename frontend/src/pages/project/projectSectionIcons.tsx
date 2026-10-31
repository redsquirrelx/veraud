import type { ReactNode } from "react"

function SectionIcon({ children }: { children: ReactNode }) {
  return <svg width={16} height={16} viewBox="0 0 16 16" fill="none" stroke="currentColor"
    strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
}

export function ProjectOverviewIcon() {
  return <SectionIcon>
    <rect x="3" y="1.5" width="10" height="13" rx="1" />
    <path d="M5.5 5h5M5.5 8h5M5.5 11h3" />
  </SectionIcon>
}

export function ProjectAnalysisIcon() {
  return <SectionIcon>
    <circle cx="6.5" cy="6.5" r="4.5" />
    <path d="m10 10 4 4" />
  </SectionIcon>
}

export function ProjectAuditsIcon() {
  return <SectionIcon>
    <path d="M5 3H3.5a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V4a1 1 0 0 0-1-1H11" />
    <rect x="5" y="1.5" width="6" height="3" rx="1" />
    <path d="m5 8 1 1 1.5-2M9.5 8h1.5M5 11.5h6" />
  </SectionIcon>
}
