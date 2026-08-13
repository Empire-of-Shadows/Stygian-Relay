import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { ErrorBoundary } from "./_engine/components/ErrorBoundary";
// Order matters: tokens define every --eos-* custom property, the engine layout
// layer reads them, and relay's own theme sits last so it can override.
import "./_engine/styles/eos-tokens.css";
import "./_engine/styles/eos-layout.css";
import "./styles/site-theme.css";

const container = document.getElementById("root");
if (!container) throw new Error("root element not found");

createRoot(container).render(
  <React.StrictMode>
    <BrowserRouter>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </BrowserRouter>
  </React.StrictMode>
);
