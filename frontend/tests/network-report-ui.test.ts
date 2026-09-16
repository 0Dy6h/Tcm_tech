import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const testFilePath = fileURLToPath(import.meta.url);

function getSource(relativePath: string) {
  return readFileSync(resolve(testFilePath, "..", "..", relativePath), "utf8");
}

test("network analysis client exposes completed-result markdown export", () => {
  const clientSource = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(clientSource, /DownloadOutlined/);
  assert.match(clientSource, /fetchNetworkReportMarkdown/);
  assert.match(clientSource, /buildNetworkReportFileName/);
  assert.match(clientSource, /aria-label="导出报告为 Markdown"/);
  assert.match(clientSource, />\s*导出报告为 Markdown\s*</);
});

test("network analysis requires an explicit research protocol and surfaces readiness blockers", () => {
  const clientSource = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(clientSource, /研究协议（运行前冻结）/);
  assert.match(clientSource, /aria-label="特应性皮炎研究表型"/);
  assert.match(clientSource, /aria-label="网络药理学证据策略"/);
  assert.match(clientSource, /aria-label="网络药理学查询日期"/);
  assert.match(clientSource, /Homo sapiens/);
  assert.match(clientSource, /科研就绪门禁/);
  assert.match(clientSource, /formal_network_ready/);
  assert.match(clientSource, /blocking_reasons/);
});

test("network analysis shows separate target sets and row-level lineage without inventing intersections", () => {
  const clientSource = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(clientSource, /靶点集合与逐行 Lineage/);
  assert.match(clientSource, /疾病靶点/);
  assert.match(clientSource, /成分靶点/);
  assert.match(clientSource, /派生候选交集/);
  assert.match(clientSource, /未采集独立疾病靶点集合/);
  assert.match(clientSource, /服务端核验的疾病靶点 artifact 在当前阈值下零命中/);
  assert.match(clientSource, /禁止从成分靶点集合自我构造疾病交集/);
  assert.match(clientSource, /原始 ID/);
  assert.match(clientSource, /标准符号/);
  assert.match(clientSource, /数据库版本/);
  assert.match(clientSource, /标识符映射/);
  assert.match(clientSource, /人工判定/);
  assert.match(clientSource, /target_lineage\.disease_targets/);
  assert.match(clientSource, /target_lineage\.compound_targets/);
  assert.match(clientSource, /target_lineage\.intersection_targets/);
  assert.match(clientSource, /disease_lineage_row_ids/);
  assert.match(clientSource, /compound_lineage_row_ids/);
});

test("network analysis verifies a raw disease-target artifact on the server and surfaces provenance", () => {
  const clientSource = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(clientSource, /UploadOutlined/);
  assert.match(clientSource, /verifyNetworkDiseaseImport/);
  assert.match(clientSource, /aria-label="选择 Open Targets 原始导出文件"/);
  assert.match(clientSource, /accept="\.json,application\/json"/);
  assert.match(clientSource, /Open Targets release/);
  assert.match(clientSource, /Usage \/ license note/);
  assert.match(clientSource, /disease_import_provenance/);
  assert.match(clientSource, /server_verified_raw_artifact/);
  assert.match(clientSource, /source_artifact_sha256/);
  assert.match(clientSource, /usage_license_note/);
  assert.match(clientSource, /服务端原始文件核验/);
});

test("network analysis verifies a raw compound-target artifact from the current owned disease task", () => {
  const clientSource = getSource("components/NetworkAnalysisClient.tsx");
  const compoundImportStart = clientSource.indexOf('aria-label="成分靶点原始 artifact"');
  const compoundImportForm = clientSource.slice(
    clientSource.lastIndexOf("<form", compoundImportStart),
    clientSource.indexOf("</form>", compoundImportStart) + "</form>".length,
  );

  assert.match(clientSource, /verifyNetworkCompoundImport/);
  assert.match(clientSource, /aria-label="选择 ChEMBL 成分靶点原始文件"/);
  assert.match(clientSource, /成分靶点原始 artifact/);
  assert.match(clientSource, /disease_import_provenance\?\.provenance_verification_status/);
  assert.match(clientSource, /result\.task_id/);
  assert.match(clientSource, /compound_import_provenance/);
  assert.match(clientSource, /source_artifact_sha256/);
  assert.match(clientSource, /result\.source_task_id \? \(/);
  assert.match(clientSource, /父疾病任务引用/);
  assert.match(clientSource, /formal_network_ready=false/);
  assert.notEqual(compoundImportStart, -1, "expected a compound import form");
  assert.match(compoundImportForm, /<fieldset disabled=\{isBusy\}>/);
  assert.match(compoundImportForm, /disabled=\{!compoundRawArtifact \|\| isBusy\}/);
  assert.doesNotMatch(clientSource, /name="owner_id"/);
  assert.doesNotMatch(clientSource, /name="reviewer_id"/);
});

test("network analysis client downloads the report through a browser blob", () => {
  const clientSource = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(clientSource, /await fetchNetworkReportMarkdown\(result\.task_id\)/);
  assert.match(clientSource, /new Blob\(\[markdown\], \{ type: "text\/markdown;charset=utf-8" \}\)/);
  assert.match(clientSource, /URL\.createObjectURL\(blob\)/);
  assert.match(clientSource, /anchor\.download = fileName/);
  assert.match(clientSource, /URL\.revokeObjectURL\(url\)/);
  assert.match(clientSource, /setErrorMessage\(describeApiError\(error, "导出报告"\)\)/);
});

test("network page surfaces a prominent mock-data boundary note", () => {
  const pageSource = getSource("app/network/page.tsx");

  assert.match(pageSource, /aria-label="机制线索演示数据说明"/);
  assert.match(pageSource, /演示数据边界/);
  assert.match(pageSource, /不可作为科研发表、临床决策或真实数据库分析结果/);
});
