import { beforeEach, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ExecutionError } from "./ExecutionError.tsx"
import { changeLanguage } from "../i18n/index.ts"
import { hiddenErrorMessage, publicErrorMessages } from "../../infrastructure/http-client/publicErrors.ts"

const secrets = ["sk-proj-fake-key-only-for-tests", "password=fake-password-731",
  "Authorization: Bearer fake-bearer-942", "https://fake-user:fake-pass@provider.invalid?api_key=fake-query-315"]

beforeEach(async () => { await changeLanguage("en") })

it.each(secrets)("hides an unverifiable historical error without receiving any credential configuration: %s", async (secret) => {
  render(<ExecutionError identity="security · #child" error={secret} />)
  await userEvent.click(screen.getByRole("button", { name: /View error/ }))
  expect(screen.getByRole("dialog")).toHaveTextContent(hiddenErrorMessage)
  expect(document.body.innerHTML).not.toContain(secret)
})

it.each(secrets)("reconstructs structured messages even when a callback claims a safe error code: %s", async (secret) => {
  render(<ExecutionError identity="security · #child" detail={{ agentId: "security", invocationId: "child",
    occurredAt: "2026-10-30T12:00:00Z", code: "execution_timeout", exceptionType: "TimeoutError", message: secret }} />)
  await userEvent.click(screen.getByRole("button", { name: /View error/ }))
  expect(screen.getByRole("dialog")).toHaveTextContent(publicErrorMessages.execution_timeout)
  expect(document.body.innerHTML).not.toContain(secret)
})
