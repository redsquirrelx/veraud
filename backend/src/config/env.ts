import { existsSync } from "node:fs"
import { fileURLToPath } from "node:url"
import dotenv from "dotenv"
import { logger } from "./logger.js"

const log = {
  error(message: string, data?: object): void {
    try {
      logger.withTag("env").error(message, data)
    } catch {
      console.error(message, data ?? "")
    }
  }
}

const ENV_FILE = fileURLToPath(new URL("../../../.env", import.meta.url))

if (!existsSync(ENV_FILE)) {
  log.error(`Can't proceed: Couldn't find .env file. It's expected: ${ENV_FILE}`)
  process.exitCode = 1
  process.exit(1)
}

dotenv.config({ path: ENV_FILE, quiet: true })

const errors: string[] = []

function getText(name: string): string {
  const value = process.env[name]?.trim() ?? ""

  if (value === "") {
    errors.push(`A mandatory variable is missing: ${name}`)
  }

  return value
}

function getPort(name: string): number {
  const value = process.env[name]?.trim() ?? ""
  
  if (value === "") {
    errors.push(`A mandatory variable is missing: ${name}`)
    return 0
  }

  const number = Number(value)

  if (!Number.isInteger(number) || number < 1 || number > 65535) {
    errors.push(`${name} must be between 1 and 65535 (value: "${value}")`)
    return 0
  }

  return number
}

export const env = Object.freeze({
  PORT_BACKEND:         getPort("PORT_BACKEND"),
  PORT_AGENTSERVER:     getPort("PORT_AGENTSERVER"),
  DATABASE_URL:         getText("DATABASE_URL"),
})

if (errors.length > 0) {
  log.error("Can't proceed: .env file is missing the mandatory variables.", { errors })
  process.exitCode = 1
  process.exit(1)
}
