import { createBrowserRouter } from "react-router-dom"
import { AppLayout } from "./layout.tsx"
import { HomePage } from "../pages/home/HomePage.tsx"
import { ProjectDetailPage } from "../pages/project/ProjectDetailPage.tsx"
import { SettingsPage } from "../pages/settings/SettingsPage.tsx"
import { ComponentTestPage } from "../pages/test/ComponentTestPage.tsx"
import { TestSelectorPage } from "../pages/test-selector/TestSelectorPage.tsx"
import { TestSidebarPage } from "../pages/test-sidebar/TestSidebarPage.tsx"

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: "projects/:id", element: <ProjectDetailPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "test", element: <ComponentTestPage /> },
      { path: "test/selector", element: <TestSelectorPage /> },
      { path: "test_sidebar", element: <TestSidebarPage /> },
    ],
  },
])
