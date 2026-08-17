import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders a hydration-stable portal shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /PolymerLit Extractor/);
  assert.match(html, /正在加载文献抽取工作台/);
  assert.match(html, /lucide-flask-conical/);
  assert.doesNotMatch(html, /class="anticon/);
});

test("ships the real candidate JSON and source PDF", async () => {
  const jsonUrl = new URL("../dist/client/data/reference_no_0101911_candidate.json", import.meta.url);
  const pdfUrl = new URL("../dist/client/papers/reference_no_0101911.pdf", import.meta.url);
  await Promise.all([access(jsonUrl), access(pdfUrl)]);

  const data = JSON.parse(await readFile(jsonUrl, "utf8"));
  assert.equal(data.paper.ref_no, "reference_no_0101911");
  assert.equal(data.paper.doi, "10.1002/app.56573");
  assert.equal(data.publication.validation_status, "not_validated");
  assert.equal(data.polymer_entities.length, 13);
  assert.equal(data.samples.length, 6);
  assert.equal(data.property_observations.length, 4);
  assert.equal(data.evidence.length, 68);
});

test("keeps candidate limitations visible in the implementation", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /不可直接入库或统计分析/);
  assert.match(page, /warningLabels/);
  assert.match(page, /property_observations/);
  assert.match(page, /evidence_ids/);
  assert.match(page, /PolymerDirectory/);
  assert.match(page, /PolymerPage/);
  assert.match(page, /SamplePage/);
  assert.match(page, /relatedProcessSteps/);
  assert.match(page, /工艺与样品谱系/);
  assert.match(page, /input_sample_ids \/ output_sample_ids/);
  assert.match(page, /systemPid/);
  assert.match(page, /PolymerStructure/);
  assert.match(page, /EvidenceVisual/);
  assert.match(page, /pageImageUrl = `\$\{pdfUrl\}\/pages\/\$\{page\}`/);
  assert.match(page, /graph-stage-headings/);
  assert.match(page, /样品中心实验知识图谱/);
  assert.match(page, /KnowledgeGraph/);
  assert.match(page, /\/graph/);
  assert.match(page, /PolyInfoResultsPage/);
  assert.match(page, /PolyInfoComparisonDrawer/);
  assert.match(page, /\/api\/polyinfo-results/);
  assert.match(page, /property_alignment/);
  assert.match(page, /本次性质阶段未生成可用观测/);
  assert.match(page, /上传高分子论文并运行抽取/);
  assert.match(page, /\/api\/tasks/);
  assert.match(page, /文档解析与加载/);
  assert.doesNotMatch(page, /@ant-design\/icons/);
});

test("uses MinerU normalized bbox coordinates and places source metadata below the visual", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /const sourceWidth = 1000;/);
  assert.match(page, /const sourceHeight = 1000;/);
  assert.doesNotMatch(page, /sourceWidth \* pageAspect/);

  const drawerStart = page.indexOf("function EvidenceDrawer");
  const visualIndex = page.indexOf("<EvidenceVisual", drawerStart);
  const locationIndex = page.indexOf('className="evidence-location evidence-location-below"', drawerStart);
  assert.ok(drawerStart >= 0 && visualIndex > drawerStart);
  assert.ok(locationIndex > visualIndex);
});
