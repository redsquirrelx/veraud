import "i18next"
import type { defaultNS, resources } from "./resources.ts"

declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: typeof defaultNS
    resources: typeof resources.en
    strictKeyChecks: true
  }
}
