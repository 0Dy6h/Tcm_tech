import { spawn } from "node:child_process";

const port = process.env.QIYAN_E2E_FRONTEND_PORT ?? "3000";
const backendPort = process.env.QIYAN_E2E_BACKEND_PORT ?? "8010";

const pnpmEntrypoint = process.env.npm_execpath;
const command = pnpmEntrypoint ? process.execPath : process.platform === "win32" ? "pnpm.cmd" : "pnpm";
const args = pnpmEntrypoint
  ? [pnpmEntrypoint, "dev", "--hostname", "127.0.0.1", "--port", port]
  : ["dev", "--hostname", "127.0.0.1", "--port", port];

// Node 20+ refuses to spawn .cmd / .bat with shell:false (CVE-2024-27980). When
// playwright invokes us via `node ./e2e/start-frontend.mjs`, npm_execpath is
// unset so we fall back to `pnpm.cmd` on Windows — that path needs shell:true.
const needsShell = !pnpmEntrypoint && process.platform === "win32";

const child = spawn(command, args, {
  env: {
    ...process.env,
    NEXT_PUBLIC_API_BASE_URL: `http://127.0.0.1:${backendPort}`,
  },
  shell: needsShell,
  stdio: "inherit",
});

const forwardSignal = (signal) => {
  child.kill(signal);
};

process.on("SIGINT", forwardSignal);
process.on("SIGTERM", forwardSignal);

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
