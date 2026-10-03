import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import path from 'path'

/// <reference types="vitest/config" />

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, path.resolve(process.cwd(), ".."), '')

  return {
    plugins: [ react() ],
    envDir: "..",
    server: {
      port: Number(env.PORT_FRONTEND ?? 5173)
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test-setup.ts"]
    }
  }
})
