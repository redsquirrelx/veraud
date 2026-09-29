import Fastify from "fastify";

const app = Fastify({
  logger: true
});

app.get("/status", async () => {
  return {
    status: "ok",
    service: "backend"
  }
})

app.listen({
  port: Number(process.env.PORT_BACKEND ?? 3000)
});