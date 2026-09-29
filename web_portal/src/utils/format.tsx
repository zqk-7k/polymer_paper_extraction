import type { CandidateData, JobStage, PolymerEntity, PropertyObservation, RepeatUnitDefinition } from "../types";

export { confidenceTag } from "../components/common";

export const stageCatalog = [
  { id: "stage0", name: "文档解析与加载", en: "Document Parsing", detail: "解析 PDF、表格、图片、页码和版面块" },
  { id: "stage1", name: "材料指称识别", en: "Material Mention", detail: "定位聚合物、添加剂、缩写和商品名" },
  { id: "stage2", name: "聚合物实体归一", en: "Entity Resolution", detail: "统一名称并保留无法确定的歧义" },
  { id: "stage3", name: "样品与加工过程", en: "Sample & Process", detail: "恢复样品、配方及过程输入输出关系" },
  { id: "stage4", name: "性质与测量条件", en: "Property Extraction", detail: "抽取性质值、单位、方法和测试条件" },
  { id: "stage5", name: "表征与证据绑定", en: "Characterization", detail: "记录表征结果并绑定原文证据" },
  { id: "result", name: "候选结果构建", en: "Result Building", detail: "汇总候选 JSON、警告和可审核记录" },
];
export const warningLabels: Record<string, string> = {
  section_fallback: "章节回退：仅使用已有证据块，需人工复核",
  preview_nested_mentions_split_retained: "嵌套材料指称的合并关系尚未完全确定",
  missing_mentions_marked_unresolved: "模型漏覆盖的材料指称已保守标记为未解析",
  preview_duplicate_mention_recovered: "重复指称仅在唯一匹配时恢复归属",
  unresolved_mentions: "存在尚未解析到统一实体的材料指称",
  unresolved_entities: "存在尚未绑定到样品的材料实体",
};
export function formatBytes(bytes: number) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index > 1 ? 2 : 0)} ${units[index]}`;
}
export function sampleKindLabel(kind?: string) {
  const labels: Record<string, string> = {
    commercial_batch: "商业批次",
    synthesis_batch: "合成批次",
    processed_material: "加工材料",
  };
  return labels[kind || ""] || kind || "未说明";
}
export function sampleDisplayName(sample: CandidateData["samples"][number]) {
  return sample.sample_label_raw?.trim() || sample.polymer_name?.trim() || sample.sample_id;
}
export function processTypeLabel(processType?: string) {
  const labels: Record<string, string> = {
    polymerization: "聚合",
    copolymerization: "共聚",
    mixing: "混合 / 共混",
    melt_blending: "熔融共混",
    solution_blending: "溶液共混",
    annealing: "退火",
    quenching: "淬火",
    drying: "干燥",
    casting: "浇铸",
    molding: "成型",
    extrusion: "挤出",
    spinning: "纺丝",
    stretching: "拉伸",
  };
  return labels[processType || ""] || processType || "未命名工艺";
}
export function processParameterText(value: unknown) {
  if (value === null || value === undefined || value === "") return "未报告";
  if (Array.isArray(value)) return value.map(processParameterText).join("；");
  if (typeof value === "object") return Object.entries(value as Record<string, unknown>).map(([key, item]) => `${key}: ${processParameterText(item)}`).join("；");
  return String(value);
}
export function stageStatusLabel(status: JobStage["status"]) {
  return { pending: "等待中", running: "进行中", complete: "已完成", failed: "失败" }[status];
}
export function displayPaperTitle(paper?: CandidateData["paper"] | null, fallback = "未识别题名") {
  return paper?.title?.trim() || paper?.ref_no?.trim() || fallback;
}
export function displayPaperAuthors(authors: unknown) {
  if (Array.isArray(authors)) return authors.filter(Boolean).join(", ") || "未识别";
  return typeof authors === "string" && authors.trim() ? authors : "未识别";
}
export function displayPaperMeta(paper?: CandidateData["paper"] | null) {
  return [paper?.journal, paper?.year].filter(Boolean).join(" · ") || "元数据待补充";
}
export function formatTaskTime(value?: string | null) {
  if (!value) return "时间未知";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}
export const repeatUnitLibrary: Record<string, RepeatUnitDefinition> = {
  "polyethylene": { formula: "C2H4", backbone: <><span>CH<sub>2</sub></span><i>–</i><span>CH<sub>2</sub></span></> },
  "polyethene": { formula: "C2H4", backbone: <><span>CH<sub>2</sub></span><i>–</i><span>CH<sub>2</sub></span></> },
  "polypropylene": { formula: "C3H6", backbone: <><span>CH<sub>2</sub></span><i>–</i><span>CH(CH<sub>3</sub>)</span></> },
  "poly(prop-1-ene)": { formula: "C3H6", backbone: <><span>CH<sub>2</sub></span><i>–</i><span>CH(CH<sub>3</sub>)</span></> },
  "poly(but-1-ene)": { formula: "C4H8", backbone: <><span>CH<sub>2</sub></span><i>–</i><span>CH(CH<sub>2</sub>CH<sub>3</sub>)</span></> },
  "polyvinyl chloride": { formula: "C2H3Cl", backbone: <><span>CH<sub>2</sub></span><i>–</i><span>CH(Cl)</span></> },
  "poly(vinyl chloride)": { formula: "C2H3Cl", backbone: <><span>CH<sub>2</sub></span><i>–</i><span>CH(Cl)</span></> },
  "polystyrene": { formula: "C8H8", backbone: <><span>CH<sub>2</sub></span><i>–</i><span>CH(C<sub>6</sub>H<sub>5</sub>)</span></> },
  "polybutadiene": { formula: "C4H6", backbone: <><span>CH<sub>2</sub></span><i>–</i><span>CH=CH</span><i>–</i><span>CH<sub>2</sub></span></>, note: "仅表示 1,4-重复单元；微观结构需原文确认" },
};
export function normalizePolymerName(name?: string) {
  return (name || "").trim().toLowerCase().replace(/\s+/g, " ");
}
export function systemPid(entity: PolymerEntity) {
  const text = normalizePolymerName(entity.polymer_name) || entity.entity_id;
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `PL-${(hash >>> 0).toString(16).toUpperCase().padStart(8, "0")}`;
}
export function repeatUnitFor(entity: PolymerEntity) {
  const record = entity as unknown as Record<string, unknown>;
  const explicitFormula = record.cu_formula || record.repeat_unit_formula;
  const known = repeatUnitLibrary[normalizePolymerName(entity.polymer_name)];
  return {
    formula: typeof explicitFormula === "string" && explicitFormula.trim() ? explicitFormula : known?.formula || null,
    definition: known || null,
  };
}
export function polymerTypeLabel(type?: string, name?: string) {
  const labels: Record<string, string> = {
    homopolymer: "Homopolymer",
    copolymer: "Copolymer",
    random_copolymer: "Random copolymer",
    block_copolymer: "Block copolymer",
    graft_copolymer: "Graft copolymer",
    terpolymer: "Terpolymer",
    blend: "Polymer blend",
    composite: "Composite",
  };
  if (type && labels[type]) return labels[type];
  const normalized = normalizePolymerName(name);
  if (normalized.includes("blend") || normalized.includes("composite") || normalized.includes("/")) return "Blend / composite";
  if (normalized.includes("terpolymer")) return "Terpolymer";
  if (normalized.includes("copolymer")) return "Copolymer";
  if (repeatUnitLibrary[normalized]) return "Homopolymer";
  return "待确认";
}
export function measurementConditionText(candidate: CandidateData, property: PropertyObservation) {
  const condition = candidate.measurement_conditions?.find((item) => item.condition_id === property.measurement_condition_id);
  const entries = Object.entries(condition?.other_conditions || property.measurement_context?.other_conditions || {});
  if (entries.length) return entries.map(([key, value]) => `${key}: ${String(value)}`).join("；");
  return condition?.condition_status === "reported" ? "原文已报告，待标准化" : "未报告";
}
