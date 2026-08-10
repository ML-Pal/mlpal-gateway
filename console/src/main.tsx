import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { Toaster } from "sonner";

import App from "@/App";
import { ConnectionProvider } from "@/lib/connection";
import { initTheme } from "@/lib/theme";
import "@/index.css";

initTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ConnectionProvider>
      <BrowserRouter>
        <App />
        <Toaster richColors position="top-right" />
      </BrowserRouter>
    </ConnectionProvider>
  </StrictMode>,
);
