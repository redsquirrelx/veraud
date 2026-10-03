import { createBrowserRouter } from "react-router-dom"
import { AppLayout } from "./layout.tsx"
import { HomePage } from "../pages/home/HomePage.tsx"
import { ComponentTestPage } from "../pages/test/ComponentTestPage.tsx"

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: "test", element: <ComponentTestPage /> },
    ],
  },
])
