import type { FastifyBaseLogger } from 'fastify'

export interface AppLogger {
  info(message: string, data?: object): void
  warn(message: string, data?: object): void
  error(message: string, data?: object): void
  debug(message: string, data?: object): void
}

let rootLogger: FastifyBaseLogger | null = null

function createLogger(tag: string): AppLogger {
  if (!rootLogger) {
    throw new Error('Logger has not been initialized')
  }

  const log = rootLogger.child({ "tag": tag })

  return {
    info(message, data) {
      log.info(data, message)
    },

    warn(message, data) {
      log.warn(data, message)
    },

    error(message, data) {
      log.error(data, message)
    },

    debug(message, data) {
      log.debug(data, message)
    },
  }
}

export const logger = {
  configure(baseLogger: FastifyBaseLogger): void {
    rootLogger = baseLogger
  },

  withTag(tag: string): AppLogger {
    return createLogger(tag)
  },
}