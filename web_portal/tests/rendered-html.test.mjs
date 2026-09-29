import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("portal shell renders PolymerLit Extractor boot state", async () => {
  const app = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
  assert.match(app, /PolymerLit Extractor/);
  assert.match(app, /正在加载文献抽取工作台/);
  assert.match(app, /最新进化结果/);
  assert.match(app, /\/api\/reports\/evolution/);
  assert.match(app, /不可直接入库或统计/);
});

test("candidate limitation copy stays visible", async () => {
  const app = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
  assert.match(app, /尚未完成科学语义校验/);
  assert.match(app, /请以原文证据与 PDF 为准/);
});
