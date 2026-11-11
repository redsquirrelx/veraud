import type { ParseKeys } from "i18next"

/** Only controlled, translated errors cross into the page; never provider bodies. */
export class ProjectPipelineError extends Error {
  readonly labelKey: ParseKeys<"projects">
  constructor(labelKey: ParseKeys<"projects">) {
    super(labelKey)
    this.labelKey = labelKey
  }
}
