import Fastify from "fastify";

const app = Fastify({
  logger: true
});

app.get("/", async () => {
  return {
    message: "Backend funcionando"
  };
});

app.listen({
  port: Number(process.env.PORT_BACKEND ?? 3000)
});