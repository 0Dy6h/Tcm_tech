import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const testFilePath = fileURLToPath(import.meta.url);

function getSource(relativePath: string) {
  return readFileSync(resolve(testFilePath, "..", "..", relativePath), "utf8");
}

test("network analysis client reads focus param from URL via useSearchParams", () => {
  const clientSource = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(clientSource, /import \{ useSearchParams \} from "next\/navigation"/);
  assert.match(clientSource, /const searchParams = useSearchParams\(\)/);
  assert.match(clientSource, /searchParams\.get\("focus"\)/);
});

test("focus deep links only prefill the form and never auto-run an analysis", () => {
  const clientSource = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(clientSource, /fetchNetworkEntities\(\)/);
  // herb and formula entities prefill their own analysis type; nothing else is prefilled
  assert.match(clientSource, /entity\.kind === "herb" \|\| entity\.kind === "formula"/);
  assert.match(clientSource, /setAnalysisType\(entity\.kind\)/);
  // one-shot guard: appliedFocusRef prevents re-prefill on re-renders
  assert.match(clientSource, /appliedFocusRef\.current === focusEntityId/);
  // focus is a navigation, not a write: the old auto-run is deliberately removed
  assert.doesNotMatch(clientSource, /void runAnalysis\(nextQuery, nextType\)/);
  // compound/target/pathway deep links explain themselves instead of prefilling
  assert.match(clientSource, /不作为分析对象/);
});

test("network 404 deep links get a distinct message and a recovery link instead of a backend-down claim", () => {
  const clientSource = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(clientSource, /error instanceof ApiStatusError && error\.status === 404/);
  assert.match(clientSource, /未找到该任务：任务可能不存在、已被删除，或不属于当前环境。/);
  assert.match(clientSource, /\{ href: "\/tasks", label: "← 回到我的研究" \}/);
  // 非 404 的 HTTP 错误带状态码如实呈现；只有真网络故障保留 backend 提示
  assert.match(clientSource, /轮询任务结果失败（HTTP \$\{error\.status\}），请稍后重试；/);
  assert.match(clientSource, /轮询任务结果失败，请确认后端服务已启动/);
});

test("network fetchers surface HTTP status via ApiStatusError", () => {
  const networkSource = getSource("lib/api/network.ts");
  const clientSource = getSource("lib/api/client.ts");

  assert.match(networkSource, /throw new ApiStatusError\(response\.status, "Network result request failed"\)/);
  assert.match(networkSource, /import \{ ApiStatusError, apiFetch, buildApiHeaders \} from "\.\/client"/);
  assert.match(clientSource, /export class ApiStatusError extends Error/);
});

test("network page wraps the client in Suspense so useSearchParams can prerender", () => {
  const pageSource = getSource("app/network/page.tsx");

  assert.match(pageSource, /import \{ Suspense \} from "react"/);
  assert.match(pageSource, /<Suspense[\s\S]*<NetworkAnalysisClient \/>/);
});
