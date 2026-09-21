import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  input: {
    public: fileURLToPath(new URL("./index.html", import.meta.url)),
    admin: fileURLToPath(new URL("./admin/index.html", import.meta.url)),
  },
});
