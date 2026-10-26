import type { RouteObject } from "react-router";
import { AppShell } from "./components/AppShell";
import { ActivityDetailPage } from "./pages/ActivityDetail";
import { ExplorerPage } from "./pages/Explorer";
import { ImportPage } from "./pages/Import";
import { LabPage } from "./pages/Lab";
import { MethodPage } from "./pages/Method";
import { MmrComparePage, MmrExplainPage, MmrOverviewPage } from "./pages/Mmr";
import { NotFoundPage } from "./pages/NotFound";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <MmrOverviewPage /> },
      { path: "mmr/compare", element: <MmrComparePage /> },
      { path: "mmr/explain", element: <MmrExplainPage /> },
      { path: "activities", element: <ExplorerPage /> },
      { path: "activities/:activityId", element: <ActivityDetailPage /> },
      { path: "import", element: <ImportPage /> },
      { path: "method", element: <MethodPage /> },
      { path: "lab", element: <LabPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
