import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { RouterProvider } from "react-router-dom"
import "@fontsource/geist/400.css"
import "@fontsource/geist/500.css"
import "@fontsource/geist/600.css"
import "@fontsource/jetbrains-mono/400.css"
import "@fontsource/jetbrains-mono/500.css"
import "./shared/styles/tokens.css"
import "./index.css"
import { AppProviders } from "./app/providers.tsx"
import { router } from "./app/router.tsx"
import { initializeI18n } from "./shared/i18n/index.ts"

async function bootstrap() {
  try {
    await initializeI18n()
  } catch {
    // Render anyway; i18next falls back to English resources.
  }

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <AppProviders>
        <RouterProvider router={router} />
      </AppProviders>
    </StrictMode>
  )
}

void bootstrap()
