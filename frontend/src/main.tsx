import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { LanguageProvider } from "./i18n";
import { operatorQueryDefaults } from "./lib/query-defaults";
import "./styles/base.css";
import "./styles/shell.css";
import "./styles/ui.css";
import "./styles/dashboard.css";
import "./styles/settings.css";
import "./styles/workspace-pages.css";
import "./styles/chat.css";
import "./styles/search.css";
import "./styles/transitions.css";

const client = new QueryClient({
  defaultOptions: {
    queries: operatorQueryDefaults,
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <LanguageProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </LanguageProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
