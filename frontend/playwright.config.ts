import { fileURLToPath } from "node:url";

import { defineConfig } from "@playwright/test";

const repositoryRoot = fileURLToPath(new URL("../", import.meta.url));
const defaultPythonExecutable = fileURLToPath(
  new URL(
    process.platform === "win32"
      ? "../.venv/Scripts/python.exe"
      : "../.venv/bin/python",
    import.meta.url,
  ),
);
const pythonExecutable =
  process.env.BEAUTYHUB_PYTHON ?? defaultPythonExecutable;
const quotedPythonExecutable = `"${pythonExecutable.replaceAll('"', '\\"')}"`;
const browserNames = ["chromium", "webkit"] as const;
const viewportWidths = [320, 390, 768, 1280] as const;

export default defineConfig({
  testDir: "./e2e",
  testIgnore: ["admin-staff-invitation.spec.ts", "admin-email-change.spec.ts"],
  outputDir: "./test-results",
  workers: 1,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:8000",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: browserNames.flatMap((browserName) =>
    viewportWidths.map((width) => ({
      name: `${browserName}-${width}`,
      use: {
        browserName,
        viewport: { height: 900, width },
      },
    })),
  ),
  webServer: {
    command: `${quotedPythonExecutable} -m uvicorn backend.app.web.app:app --host 127.0.0.1 --port 8000`,
    cwd: repositoryRoot,
    reuseExistingServer: false,
    timeout: 120_000,
    url: "http://127.0.0.1:8000",
  },
});
