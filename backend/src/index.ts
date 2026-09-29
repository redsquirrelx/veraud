import Fastify from "fastify";
import { logger } from "./config/logger.js"

const app = Fastify({
  logger: {
    transport: {
      target: "pino-pretty",
      options: {
        colorize: true,
        translateTime: 'HH:MM:ss',
        ignore: 'pid,hostname',
      },
    }
  }
});

logger.configure(app.log)

app.get("/status", async () => {
  const log = logger.withTag("status")
  log.info("Status requested")

  return {
    status: "ok",
    service: "backend"
  }
})

app.listen({
  port: Number(process.env.PORT_BACKEND ?? 3000)
});