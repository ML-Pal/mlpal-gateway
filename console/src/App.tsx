import { Navigate, Route, Routes } from "react-router";

import { Layout } from "@/components/Layout";
import { useConnection } from "@/lib/connection";
import { Catalog } from "@/pages/Catalog";
import { Keys } from "@/pages/Keys";
import { Models } from "@/pages/Models";
import { Overview } from "@/pages/Overview";
import { Playground } from "@/pages/Playground";
import { Providers } from "@/pages/Providers";
import { Settings } from "@/pages/Settings";
import { Setup } from "@/pages/Setup";
import { Traces } from "@/pages/Traces";
import { Usage } from "@/pages/Usage";

export default function App() {
  const { connection } = useConnection();

  if (!connection) {
    return (
      <Routes>
        <Route path="/setup" element={<Setup />} />
        <Route path="*" element={<Navigate to="/setup" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/overview" replace />} />
        <Route path="/overview" element={<Overview />} />
        <Route path="/traces" element={<Traces />} />
        <Route path="/playground" element={<Playground />} />
        <Route path="/providers" element={<Providers />} />
        <Route path="/keys" element={<Keys />} />
        <Route path="/models" element={<Models />} />
        <Route path="/catalog" element={<Catalog />} />
        <Route path="/usage" element={<Usage />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/overview" replace />} />
      </Route>
    </Routes>
  );
}
