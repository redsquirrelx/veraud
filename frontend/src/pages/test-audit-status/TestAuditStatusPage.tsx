import { Link } from "react-router-dom"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { AuditStatusDrawer, AuditStatusView, type AuditStatusModel } from "../../shared/audit-monitor/index.ts"
import { Card } from "../../shared/ui-kit/index.ts"
import "./TestAuditStatusPage.css"

const running: AuditStatusModel = {
  id: 41,
  project: { id: 5, repositoryOwner: "acme", repositoryName: "Payments" },
  branch: "main",
  commitHash: "9f2c1ab7de4d0c6b5a8391f4e2d7c8b0a6e5f4d3",
  state: "running",
  error: null,
  createdAt: "2026-10-17T10:00:00Z",
  finishedAt: null,
  reportAvailable: false,
  pipelines: [
    {
      id: "maintainability",
      state: "running",
      agents: [
        {
          id: 118, agentType: "maintainability_manager", state: "running",
          inputTokens: 41230, outputTokens: 9840,
          startedAt: "2026-10-17T10:00:12Z", finishedAt: null, error: null,
        },
        {
          id: 119, parentId: 118, agentType: "modularity", state: "running",
          inputTokens: 22100, outputTokens: 3120,
          startedAt: "2026-10-17T10:04:44Z", finishedAt: null, error: null,
        },
        {
          id: 120, parentId: 119, agentType: "architect_boundary", state: "waiting",
          inputTokens: null, outputTokens: null,
          startedAt: null, finishedAt: null, error: null,
        },
        {
          id: 123, parentId: 118, agentType: "reusability", state: "running",
          inputTokens: 8200, outputTokens: 1200,
          startedAt: "2026-10-17T10:04:44Z", finishedAt: null, error: null,
        },
        {
          id: 124, parentId: 123, agentType: "abstraction", state: "running",
          inputTokens: null, outputTokens: null,
          startedAt: "2026-10-17T10:04:50Z", finishedAt: null, error: null,
        },
      ],
    },
    {
      id: "security",
      state: "running",
      agents: [
        {
          id: 121, agentType: "security_scanner", state: "completed",
          inputTokens: 33880, outputTokens: 7415,
          startedAt: "2026-10-17T10:00:15Z", finishedAt: "2026-10-17T10:03:09Z", error: null,
        },
        {
          id: 122, agentType: "security_explorer", state: "running",
          inputTokens: null, outputTokens: null,
          startedAt: "2026-10-17T10:03:10Z", finishedAt: null, error: null,
        },
      ],
    },
  ],
}

const completed: AuditStatusModel = {
  id: 40,
  project: { id: 5, repositoryOwner: "acme", repositoryName: "Payments" },
  branch: "main",
  commitHash: "3b7e5f0a1c9d8e2f4a6b0c3d5e7f9a1b3c5d7e9f",
  state: "completed",
  error: null,
  createdAt: "2026-10-16T08:30:00Z",
  finishedAt: "2026-10-16T08:41:27Z",
  reportAvailable: true,
  pipelines: [
    {
      id: "maintainability",
      state: "completed",
      agents: [
        {
          id: 112, agentType: "maintainability_manager", state: "completed",
          inputTokens: 40120, outputTokens: 9120,
          startedAt: "2026-10-16T08:30:09Z", finishedAt: "2026-10-16T08:34:52Z", error: null,
        },
        {
          id: 113, agentType: "maintainability_judge", state: "completed",
          inputTokens: 19870, outputTokens: 4210,
          startedAt: "2026-10-16T08:34:55Z", finishedAt: "2026-10-16T08:38:31Z", error: null,
        },
      ],
    },
    {
      id: "security",
      state: "completed",
      agents: [
        {
          id: 114, agentType: "security_scanner", state: "completed",
          inputTokens: 31500, outputTokens: 6980,
          startedAt: "2026-10-16T08:30:11Z", finishedAt: "2026-10-16T08:33:47Z", error: null,
        },
        {
          id: 115, agentType: "security_judge", state: "completed",
          inputTokens: 17240, outputTokens: 3880,
          startedAt: "2026-10-16T08:38:34Z", finishedAt: "2026-10-16T08:41:27Z", error: null,
        },
      ],
    },
  ],
}

const partial: AuditStatusModel = {
  id: 39,
  project: { id: 12, repositoryOwner: "acme", repositoryName: "Ledger" },
  branch: "release/2.4",
  commitHash: "77c1a9e5d3b0f2a8c6e4d1b9f7a3c5e8d0b2f6a4",
  state: "partial",
  error: null,
  createdAt: "2026-10-15T14:10:00Z",
  finishedAt: "2026-10-15T14:19:44Z",
  reportAvailable: true,
  pipelines: [
    {
      id: "maintainability",
      state: "partial",
      agents: [
        {
          id: 104, agentType: "maintainability_manager", state: "completed",
          inputTokens: 38990, outputTokens: 8760,
          startedAt: "2026-10-15T14:10:08Z", finishedAt: "2026-10-15T14:15:02Z", error: null,
        },
        {
          id: 105, agentType: "maintainability_reviewer", state: "failed",
          inputTokens: 20440, outputTokens: 1120,
          startedAt: "2026-10-15T14:15:05Z", finishedAt: "2026-10-15T14:16:51Z",
          error: "Model-call limit reached before the review could finish.",
        },
        {
          id: 106, agentType: "maintainability_judge", state: "waiting",
          inputTokens: null, outputTokens: null,
          startedAt: null, finishedAt: null, error: null,
        },
      ],
    },
    {
      id: "security",
      state: "completed",
      agents: [
        {
          id: 107, agentType: "security_scanner", state: "completed",
          inputTokens: 29760, outputTokens: 6430,
          startedAt: "2026-10-15T14:10:10Z", finishedAt: "2026-10-15T14:13:55Z", error: null,
        },
      ],
    },
  ],
}

const failed: AuditStatusModel = {
  id: 38,
  // A deliberately long name: the summary rows must hold without spilling.
  project: { id: 12, repositoryOwner: "open-software-foundation-laboratory", repositoryName: "distributed-transactional-platform" },
  branch: "main",
  commitHash: "0d5e8b2a6f4c1a9e7b3d5f8a0c2e4b6d8f0a2c4e",
  state: "failed",
  error: "The security pipeline could not be started: its agents have no configured model access.",
  createdAt: "2026-10-14T11:20:00Z",
  finishedAt: "2026-10-14T11:20:03Z",
  reportAvailable: false,
  pipelines: [
    {
      id: "maintainability",
      state: "completed",
      agents: [
        {
          id: 96, agentType: "maintainability_manager", state: "completed",
          inputTokens: 36210, outputTokens: 8140,
          startedAt: "2026-10-14T11:20:06Z", finishedAt: "2026-10-14T11:25:39Z", error: null,
        },
      ],
    },
    { id: "security", state: "failed", agents: [] },
  ],
}

const fixtures: { model: AuditStatusModel, labelKey: ParseKeys<"common"> }[] = [
  { model: running, labelKey: "testPages.auditStatus.runningTitle" },
  { model: completed, labelKey: "testPages.auditStatus.completedTitle" },
  { model: partial, labelKey: "testPages.auditStatus.partialTitle" },
  { model: failed, labelKey: "testPages.auditStatus.failedTitle" },
]

const drawerHints = [
  "testPages.auditStatus.drawerHintTab",
  "testPages.auditStatus.drawerHintPanel",
  "testPages.auditStatus.drawerHintKeyboard",
] as const

export function TestAuditStatusPage() {
  const { t } = useTranslation("common")
  return (
    <section className="test-audit-status-page">
      <h1>{t("testPages.auditStatus.title")}</h1>
      <p className="label">
        <Link to="/test">{t("testPages.allPlaygrounds")}</Link> · {t("testPages.auditStatus.subtitle")}
      </p>
      {fixtures.map(({ model, labelKey }) => (
        <div className="test-audit-status-case" key={model.id}>
          <span className="label">{t(labelKey)}</span>
          <AuditStatusView audit={model} />
        </div>
      ))}
      <Card>
        <h2>{t("testPages.auditStatus.drawerTitle")}</h2>
        <p className="label">{t("testPages.auditStatus.drawerHint")}</p>
        <ul>
          {drawerHints.map((hintKey) => <li key={hintKey}>{t(hintKey)}</li>)}
        </ul>
      </Card>
      {/* Fixed to the viewport: the tab hugs the left edge over this text and
          the panel slides in from the right over the whole playground. */}
      <AuditStatusDrawer audits={fixtures.map((fixture) => fixture.model)} />
    </section>
  )
}
