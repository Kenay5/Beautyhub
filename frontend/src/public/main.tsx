import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "../shared/styles/base.css";
import { PublicApp } from "./PublicApp";

const rootElement = document.getElementById("root");

if (rootElement === null) {
  throw new Error("Public React root was not found.");
}

createRoot(rootElement).render(
  <StrictMode>
    <PublicApp />
  </StrictMode>,
);
