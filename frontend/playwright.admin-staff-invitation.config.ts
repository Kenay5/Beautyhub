import { fileURLToPath } from "node:url";

import { defineConfig } from "@playwright/test";

const repositoryRoot = fileURLToPath(new URL("../", import.meta.url));
const pythonExecutable = fileURLToPath(
  new URL(
    process.platform === "win32"
      ? "../.venv/Scripts/python.exe"
      : "../.venv/bin/python",
    import.meta.url,
  ),
);
const quotedPythonExecutable = `"${pythonExecutable.replaceAll('"', '\\"')}"`;
const browserNames = ["chromium", "webkit"] as const;
const viewportWidths = [320, 390, 768, 1280] as const;

export default defineConfig({
  testDir: "./e2e",
  testMatch: ["admin-staff-invitation.spec.ts", "admin-email-change.spec.ts"],
  outputDir: "./test-results/admin-access-security",
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "https://127.0.0.1:8443",
    ignoreHTTPSErrors: true,
    screenshot: "off",
    trace: "off",
    video: "off",
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
    command: `${quotedPythonExecutable} -m backend.tests.e2e.admin_access.serve`,
    cwd: repositoryRoot,
    reuseExistingServer: false,
    timeout: 120_000,
    url: "http://127.0.0.1:8000/health",
  },
});
