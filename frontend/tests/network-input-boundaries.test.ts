import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const testFilePath = fileURLToPath(import.meta.url);

function getSource(relativePath: string) {
  return readFileSync(resolve(testFilePath, "..", "..", relativePath), "utf8");
}

test("analysis form enforces backend-matching input bounds before submit", () => {
  const clientSource = getSource("components/NetworkAnalysisClient.tsx");

  // bounds mirror backend/app/schemas/network.py (query 1-100, phenotype 4-200)
  assert.match(clientSource, /NETWORK_QUERY_MAX_LENGTH = 100/);
  assert.match(clientSource, /NETWORK_PHENOTYPE_MIN_LENGTH = 4/);
  assert.match(clientSource, /NETWORK_PHENOTYPE_MAX_LENGTH = 200/);
  // the query input cannot overflow at the control level either
  assert.match(clientSource, /maxLength=\{NETWORK_QUERY_MAX_LENGTH\}/);
  // submit-time guards cover length, phenotype span, and future query dates
  assert.match(clientSource, /trimmedQuery\.length > NETWORK_QUERY_MAX_LENGTH/);
  assert.match(clientSource, /trimmedPhenotype\.length < NETWORK_PHENOTYPE_MIN_LENGTH/);
  assert.match(clientSource, /queryDate > toLocalDateInputValue\(new Date\(\)\)/);
  assert.match(clientSource, /查询日期不能晚于今天/);
});

test("query date input blocks future dates at the control level", () => {
  const clientSource = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(
    clientSource,
    /type="date"[\s\S]*?max=\{toLocalDateInputValue\(new Date\(\)\)\}[\s\S]*?aria-label="网络药理学查询日期"/,
  );
});

test("analyze submit failures distinguish server validation from transport errors", () => {
  const clientSource = getSource("components/NetworkAnalysisClient.tsx");

  // 422: server-side validation rejection, never claims the backend is down
  assert.match(clientSource, /error instanceof ApiStatusError && error\.status === 422/);
  assert.match(clientSource, /提交被服务端校验拒绝：请核对分析对象与研究表型（4-200 字）、查询日期后重试。/);
  // other HTTP statuses surface the status code honestly
  assert.match(clientSource, /提交分析任务失败（HTTP \$\{error\.status\}），请稍后重试；/);
  // the backend-down claim is reserved for genuine transport failures (non-ApiStatusError)
  assert.match(clientSource, /提交分析任务失败，请确认后端服务已启动/);
});

test("network POST fetchers surface HTTP status via ApiStatusError", () => {
  const networkSource = getSource("lib/api/network.ts");

  assert.match(networkSource, /throw new ApiStatusError\(response\.status, "Network analyze request failed"\)/);
  assert.match(networkSource, /throw new ApiStatusError\(response\.status, "Network disease import verification request failed"\)/);
  assert.match(networkSource, /throw new ApiStatusError\(response\.status, "Network compound import verification request failed"\)/);
  assert.match(networkSource, /throw new ApiStatusError\(response\.status, "Network adjudication request failed"\)/);
});
