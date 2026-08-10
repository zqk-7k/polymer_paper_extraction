"use client";
/* eslint-disable @next/next/no-img-element -- evidence crops reuse a dynamically rendered PDF page */

import {
  Alert,
  Button,
  ConfigProvider,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Progress,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { UploadFile } from "antd/es/upload/interface";
import {
  Archive,
  AlertTriangle,
  ArrowLeft,
  Beaker,
  Boxes,
  Check,
  ChevronRight,
  Database,
  Download,
  FileJson,
  FileSearch,
  FlaskConical,
  FolderSearch,
  Gauge,
  GitBranch,
  Link2,
  LoaderCircle,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  TableProperties,
  UploadCloud,
  Workflow,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Background, Controls, MarkerType, MiniMap, ReactFlow, type Edge, type Node, type NodeMouseHandler } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import sampleCandidate from "./data/reference_no_0101911_candidate.json";
import "./globals.css";

const { Title, Text, Paragraph } = Typography;
const { Dragger } = Upload;
const API_BASE = process.env.NEXT_PUBLIC_EXTRACTION_API_BASE_URL || "";

type ViewKey = "upload" | "history" | "batch" | "polyinfo" | "results" | "polymer" | "sample";
type CandidateData = typeof sampleCandidate;
type PolymerEntity = CandidateData["polymer_entities"][number];
type PropertyObservation = CandidateData["property_observations"][number];
type Evidence = CandidateData["evidence"][number];

type GraphNodePayload = {
  id: string;
  type: "paper" | "polymer" | "sample" | "process" | "property" | "characterization";
  label: string;
  data: Record<string, unknown>;
};

type GraphPayload = {
  nodes: GraphNodePayload[];
  edges: Array<{ id: string; source: string; target: string; type: string; label: string }>;
  stats: { node_counts: Record<string, number>; edge_count: number };
};

type JobStage = {
  id: string;
  status: "pending" | "running" | "complete" | "failed";
  artifact: string | null;
};

type ExtractionJob = {
  task_id: string;
  ref_no: string;
  source_reference_no?: string | null;
  file_name: string;
  file_size: number;
  status: "queued" | "running" | "complete" | "failed" | "cancelled";
  created_at: string;
  updated_at: string;
  current_stage: string | null;
  progress: number;
  result_ready: boolean;
  result_url: string | null;
  pdf_url: string;
  stages: JobStage[];
  error?: string | null;
  paper?: CandidateData["paper"];
  stats?: ResultStats;
  validation_status?: string | null;
  source_kind?: "web";
};

type ResultStats = {
  polymer_count: number;
  sample_count: number;
  property_count: number;
  process_count: number;
  characterization_count: number;
  evidence_count: number;
};

type BatchResultSummary = {
  source_kind: "batch";
  collection_id: string;
  result_date?: string | null;
  result_mode?: string | null;
  ref_no: string;
  source_batch?: string | null;
  result_url: string;
  graph_url: string;
  pdf_url?: string | null;
  paper: CandidateData["paper"];
  stats: ResultStats;
  validation_status?: string | null;
};

type PolyInfoStats = ResultStats & {
  property_type_count: number;
  measurement_condition_count: number;
  structure_count: number;
};

type PolyInfoSummary = {
  source_kind: "polyinfo";
  collection_id: string;
  group: string;
  ref_no: string;
  reference: { author?: string; journal?: string; year?: string; doi?: string; volume?: string; issue?: string; page?: string };
  polymer_names: string[];
  polymer_name_count: number;
  stats: PolyInfoStats;
  has_pdf: boolean;
  has_batch_result?: boolean;
  detail_url: string;
  comparison_url: string;
};

type PolyInfoProperty = {
  id: string;
  sample_id: string;
  polymer_id: string;
  category: string;
  name: string;
  value: string;
  value_min?: number | null;
  value_max?: number | null;
  unit?: string | null;
  method?: string | null;
  condition?: string | null;
  remark?: string | null;
  source: string;
};

type PolyInfoComparison = {
  ref_no: string;
  message: string;
  polyinfo: {
    group: string;
    ref_no: string;
    reference: PolyInfoSummary["reference"];
    stats: PolyInfoStats;
    pdf_url?: string | null;
    polymers: Array<{ polymer_id: string; polymer_names: string[]; polymer_type?: string; cu_formula?: string; structure_image?: string | null; sample_ids: string[] }>;
    samples: Array<{ sample_id: string; polymer_id: string; polymer_name: string[]; polymer_type?: string; polymer_class: string[]; material_type: string[]; cu_formula?: string; property_count: number; process_count: number; source_file: string }>;
    properties: PolyInfoProperty[];
    processes: Array<{ sample_id: string; kind: string; value: string }>;
  };
  extraction: null | {
    source_kind: "batch";
    collection_id: string;
    created_at: string;
    file_name: string;
    paper: CandidateData["paper"];
    stats: PolyInfoStats;
    polymer_entities: CandidateData["polymer_entities"];
    samples: CandidateData["samples"];
  };
  metrics: Array<{ key: string; label: string; polyinfo: number; extraction: number; interpretation: string }>;
  property_alignment: Array<{ status: "matched" | "value_diff" | "polyinfo_only" | "extraction_only"; canonical_name: string; polyinfo: PolyInfoProperty | null; extraction: PropertyObservation | null }>;
  alignment_stats?: Record<string, number>;
};

type HealthState = {
  status: string;
  python_ready: boolean;
  mineru_key_ready: boolean;
  llm_key_ready: boolean;
  key_submission_allowed?: boolean;
  requires_https_for_keys?: boolean;
};

const stageCatalog = [
  { id: "stage0", name: "文档解析与加载", en: "Document Parsing", detail: "解析 PDF、表格、图片、页码和版面块" },
  { id: "stage1", name: "材料指称识别", en: "Material Mention", detail: "定位聚合物、添加剂、缩写和商品名" },
  { id: "stage2", name: "聚合物实体归一", en: "Entity Resolution", detail: "统一名称并保留无法确定的歧义" },
  { id: "stage3", name: "样品与加工过程", en: "Sample & Process", detail: "恢复样品、配方及过程输入输出关系" },
  { id: "stage4", name: "性质与测量条件", en: "Property Extraction", detail: "抽取性质值、单位、方法和测试条件" },
  { id: "stage5", name: "表征与证据绑定", en: "Characterization", detail: "记录表征结果并绑定原文证据" },
  { id: "result", name: "候选结果构建", en: "Result Building", detail: "汇总候选 JSON、警告和可审核记录" },
];

const warningLabels: Record<string, string> = {
  section_fallback: "章节回退：仅使用已有证据块，需人工复核",
  preview_nested_mentions_split_retained: "嵌套材料指称的合并关系尚未完全确定",
  missing_mentions_marked_unresolved: "模型漏覆盖的材料指称已保守标记为未解析",
  preview_duplicate_mention_recovered: "重复指称仅在唯一匹配时恢复归属",
  unresolved_mentions: "存在尚未解析到统一实体的材料指称",
  unresolved_entities: "存在尚未绑定到样品的材料实体",
};

function formatBytes(bytes: number) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index > 1 ? 2 : 0)} ${units[index]}`;
}

function confidenceTag(score?: number) {
  if (score === undefined) return <Tag>未评分</Tag>;
  const color = score >= 0.9 ? "success" : score >= 0.75 ? "warning" : "error";
  return <Tag color={color}>{Math.round(score * 100)}%</Tag>;
}

function sampleKindLabel(kind?: string) {
  const labels: Record<string, string> = {
    commercial_batch: "商业批次",
    synthesis_batch: "合成批次",
    processed_material: "加工材料",
  };
  return labels[kind || ""] || kind || "未说明";
}

function sampleDisplayName(sample: CandidateData["samples"][number]) {
  return sample.sample_label_raw?.trim() || sample.polymer_name?.trim() || sample.sample_id;
}

function stageStatusLabel(status: JobStage["status"]) {
  return { pending: "等待中", running: "进行中", complete: "已完成", failed: "失败" }[status];
}

function displayPaperTitle(paper?: CandidateData["paper"] | null, fallback = "未识别题名") {
  return paper?.title?.trim() || paper?.ref_no?.trim() || fallback;
}

function displayPaperAuthors(authors: unknown) {
  if (Array.isArray(authors)) return authors.filter(Boolean).join(", ") || "未识别";
  return typeof authors === "string" && authors.trim() ? authors : "未识别";
}

function displayPaperMeta(paper?: CandidateData["paper"] | null) {
  return [paper?.journal, paper?.year].filter(Boolean).join(" · ") || "元数据待补充";
}

function formatTaskTime(value?: string | null) {
  if (!value) return "时间未知";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

type RepeatUnitDefinition = {
  formula: string;
  backbone: React.ReactNode;
  note?: string;
};

const repeatUnitLibrary: Record<string, RepeatUnitDefinition> = {
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

function normalizePolymerName(name?: string) {
  return (name || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function systemPid(entity: PolymerEntity) {
  const text = normalizePolymerName(entity.polymer_name) || entity.entity_id;
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `PL-${(hash >>> 0).toString(16).toUpperCase().padStart(8, "0")}`;
}

function repeatUnitFor(entity: PolymerEntity) {
  const record = entity as unknown as Record<string, unknown>;
  const explicitFormula = record.cu_formula || record.repeat_unit_formula;
  const known = repeatUnitLibrary[normalizePolymerName(entity.polymer_name)];
  return {
    formula: typeof explicitFormula === "string" && explicitFormula.trim() ? explicitFormula : known?.formula || null,
    definition: known || null,
  };
}

function polymerTypeLabel(type?: string, name?: string) {
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

function measurementConditionText(candidate: CandidateData, property: PropertyObservation) {
  const condition = candidate.measurement_conditions?.find((item) => item.condition_id === property.measurement_condition_id);
  const entries = Object.entries(condition?.other_conditions || property.measurement_context?.other_conditions || {});
  if (entries.length) return entries.map(([key, value]) => `${key}: ${String(value)}`).join("；");
  return condition?.condition_status === "reported" ? "原文已报告，待标准化" : "未报告";
}

function PolymerStructure({ entity, compact = false }: { entity: PolymerEntity; compact?: boolean }) {
  const repeatUnit = repeatUnitFor(entity);
  if (!repeatUnit.definition) {
    return <div className={`structure-placeholder ${compact ? "compact" : ""}`}><FlaskConical size={compact ? 18 : 24} /><strong>结构式待补充</strong><span>缺少可验证的重复单元连接信息</span></div>;
  }
  return <div className={`repeat-unit-structure ${compact ? "compact" : ""}`}><div className="repeat-bracket">[</div><div className="repeat-backbone">{repeatUnit.definition.backbone}</div><div className="repeat-bracket right">]<sub>n</sub></div>{repeatUnit.definition.note && <small>{repeatUnit.definition.note}</small>}</div>;
}

export default function Home() {
  const [mounted, setMounted] = useState(false);
  const [view, setView] = useState<ViewKey>("upload");
  const [collapsed, setCollapsed] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dmxApiKey, setDmxApiKey] = useState("");
  const [mineruApiKey, setMineruApiKey] = useState("");
  const [job, setJob] = useState<ExtractionJob | null>(null);
  const [health, setHealth] = useState<HealthState | null>(null);
  const [apiChecked, setApiChecked] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [candidate, setCandidate] = useState<CandidateData | null>(null);
  const [graphPayload, setGraphPayload] = useState<GraphPayload | null>(null);
  const [dataSource, setDataSource] = useState<"task" | "batch" | "sample" | null>(null);
  const [selectedBatch, setSelectedBatch] = useState<BatchResultSummary | null>(null);
  const [historyTasks, setHistoryTasks] = useState<ExtractionJob[]>([]);
  const [batchResults, setBatchResults] = useState<BatchResultSummary[]>([]);
  const [polyInfoResults, setPolyInfoResults] = useState<PolyInfoSummary[]>([]);
  const [polyInfoComparison, setPolyInfoComparison] = useState<PolyInfoComparison | null>(null);
  const [polyInfoComparisonLoading, setPolyInfoComparisonLoading] = useState(false);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [selectedPolymerId, setSelectedPolymerId] = useState("");
  const [selectedSampleId, setSelectedSampleId] = useState("");
  const [entitySearch, setEntitySearch] = useState("");
  const [entityFilter, setEntityFilter] = useState("all");
  const [selectedEvidence, setSelectedEvidence] = useState<Evidence | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<PolymerEntity | null>(null);
  const [messageApi, contextHolder] = message.useMessage();

  useEffect(() => {
    const timer = window.setTimeout(() => setMounted(true), 0);
    return () => window.clearTimeout(timer);
  }, []);

  const checkHealth = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/health`);
      if (!response.ok) throw new Error("API unavailable");
      setHealth(await response.json());
    } catch {
      setHealth(null);
    } finally {
      setApiChecked(true);
    }
  }, []);

  useEffect(() => {
    if (!mounted) return;
    const timer = window.setTimeout(() => void checkHealth(), 0);
    return () => window.clearTimeout(timer);
  }, [mounted, checkHealth]);

  const loadTaskResult = useCallback(async (task: ExtractionJob) => {
    if (!task.result_ready) return;
    const [response, graphResponse] = await Promise.all([
      fetch(`${API_BASE}/api/tasks/${task.task_id}/result`),
      fetch(`${API_BASE}/api/tasks/${task.task_id}/graph`),
    ]);
    if (!response.ok) throw new Error("结果文件尚不可读取");
    const data = await response.json() as CandidateData;
    setCandidate(data);
    setGraphPayload(graphResponse.ok ? await graphResponse.json() as GraphPayload : null);
    setDataSource("task");
    setSelectedBatch(null);
    setSelectedPolymerId("");
    setSelectedSampleId(data.samples[0]?.sample_id || "");
  }, []);

  const refreshHistory = useCallback(async () => {
    setArchiveLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/tasks?limit=100`);
      if (!response.ok) throw new Error("历史任务读取失败");
      setHistoryTasks(await response.json() as ExtractionJob[]);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "历史任务读取失败");
    } finally {
      setArchiveLoading(false);
    }
  }, [messageApi]);

  const refreshBatchResults = useCallback(async () => {
    setArchiveLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/batch-results`);
      if (!response.ok) throw new Error("批处理结果读取失败");
      setBatchResults(await response.json() as BatchResultSummary[]);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "批处理结果读取失败");
    } finally {
      setArchiveLoading(false);
    }
  }, [messageApi]);

  const refreshPolyInfoResults = useCallback(async () => {
    setArchiveLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/polyinfo-results`);
      if (!response.ok) throw new Error("PoLyInfo 原始数据读取失败");
      setPolyInfoResults(await response.json() as PolyInfoSummary[]);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "PoLyInfo 原始数据读取失败");
    } finally {
      setArchiveLoading(false);
    }
  }, [messageApi]);

  const openPolyInfoComparison = useCallback(async (refNo: string) => {
    setPolyInfoComparisonLoading(true);
    setPolyInfoComparison(null);
    try {
      const response = await fetch(`${API_BASE}/api/polyinfo-results/${refNo}/comparison`);
      if (!response.ok) throw new Error("PoLyInfo 对照结果读取失败");
      setPolyInfoComparison(await response.json() as PolyInfoComparison);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "PoLyInfo 对照结果读取失败");
    } finally {
      setPolyInfoComparisonLoading(false);
    }
  }, [messageApi]);

  useEffect(() => {
    if (!mounted || !health || job || candidate) return;
    const restoreLatestTask = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/tasks?limit=1`);
        if (!response.ok) return;
        const tasks = await response.json() as ExtractionJob[];
        const latest = tasks[0];
        if (!latest) return;
        setJob(latest);
        if (latest.result_ready) await loadTaskResult(latest);
      } catch {
        // Restoring the latest local task is optional; upload remains available.
      }
    };
    void restoreLatestTask();
  }, [mounted, health, job, candidate, loadTaskResult]);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const poll = window.setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE}/api/tasks/${job.task_id}`);
        if (!response.ok) return;
        const next = await response.json() as ExtractionJob;
        setJob(next);
        if (next.result_ready) await loadTaskResult(next);
      } catch {
        // A temporary polling failure should not overwrite the last real state.
      }
    }, 2000);
    return () => window.clearInterval(poll);
  }, [job, loadTaskResult]);

  const startExtraction = async () => {
    if (!selectedFile || !dmxApiKey.trim() || !mineruApiKey.trim()) return;
    setUploading(true);
    const form = new FormData();
    form.append("file", selectedFile);
    form.append("dmx_api_key", dmxApiKey.trim());
    form.append("mineru_api_key", mineruApiKey.trim());
    try {
      const response = await fetch(`${API_BASE}/api/tasks`, { method: "POST", body: form });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "任务创建失败");
      setJob(payload as ExtractionJob);
      setCandidate(null);
      setGraphPayload(null);
      setDataSource("task");
      setSelectedBatch(null);
      setSelectedPolymerId("");
      setDmxApiKey("");
      setMineruApiKey("");
      messageApi.success("论文已上传，抽取任务开始运行");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "无法连接抽取服务");
    } finally {
      setUploading(false);
    }
  };

  const loadSample = () => {
    const data = sampleCandidate as CandidateData;
    setCandidate(data);
    setGraphPayload(null);
    setDataSource("sample");
    setSelectedBatch(null);
    setSelectedPolymerId(data.samples[0]?.refers_to_entity || "");
    setSelectedSampleId(data.samples[0]?.sample_id || "");
    setJob(null);
    setView("results");
    messageApi.info("已加载内置示例；该结果不代表新上传任务");
  };

  const openResults = () => {
    setView("history");
    void refreshHistory();
  };

  const navigate = (nextView: ViewKey) => {
    setView(nextView);
    if (nextView === "history") void refreshHistory();
    if (nextView === "batch") void refreshBatchResults();
    if (nextView === "polyinfo") void refreshPolyInfoResults();
  };

  const openHistoryTask = async (task: ExtractionJob) => {
    if (!task.result_ready) {
      setJob(task);
      setView("upload");
      messageApi.info(task.status === "failed" ? "该任务执行失败，请在流水线页查看原因" : "该任务尚未完成，已切换到流水线进度");
      return;
    }
    setArchiveLoading(true);
    try {
      setJob(task);
      await loadTaskResult(task);
      setView("results");
    } catch {
      messageApi.error("历史抽取结果读取失败");
    } finally {
      setArchiveLoading(false);
    }
  };

  const openBatchResult = async (item: BatchResultSummary) => {
    setArchiveLoading(true);
    try {
      const [response, graphResponse] = await Promise.all([
        fetch(`${API_BASE}${item.result_url}`),
        fetch(`${API_BASE}${item.graph_url}`),
      ]);
      if (!response.ok) throw new Error("批处理候选结果不可读取");
      const data = await response.json() as CandidateData;
      setCandidate(data);
      setGraphPayload(graphResponse.ok ? await graphResponse.json() as GraphPayload : null);
      setDataSource("batch");
      setSelectedBatch(item);
      setSelectedPolymerId("");
      setSelectedSampleId(data.samples[0]?.sample_id || "");
      setJob(null);
      setView("results");
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "批处理候选结果读取失败");
    } finally {
      setArchiveLoading(false);
    }
  };

  const returnToResultList = () => {
    if (dataSource === "batch") {
      setView("batch");
      void refreshBatchResults();
      return;
    }
    if (dataSource === "sample") {
      setView("upload");
      return;
    }
    setView("history");
    void refreshHistory();
  };

  const openPolymerPage = (entityId: string) => {
    setSelectedPolymerId(entityId);
    setSelectedSampleId("");
    setView("polymer");
  };

  const openSamplePage = (sampleId: string) => {
    const sample = candidate?.samples.find((item) => item.sample_id === sampleId);
    if (sample?.refers_to_entity) setSelectedPolymerId(sample.refers_to_entity);
    setSelectedSampleId(sampleId);
    setView("sample");
  };

  const pdfUrl = dataSource === "task" && job
    ? `${API_BASE}/api/tasks/${job.task_id}/pdf`
    : dataSource === "batch" && selectedBatch?.pdf_url
      ? `${API_BASE}${selectedBatch.pdf_url}`
      : `${API_BASE}/api/source-pdfs/reference_no_0101911/pdf`;

  const downloadJson = () => {
    if (!candidate) return;
    const blob = new Blob([JSON.stringify(candidate, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${candidate.paper.ref_no}_candidate.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  if (!mounted) {
    return (
      <main className="portal-boot" aria-label="正在加载 PolymerLit Extractor">
        <div className="boot-logo"><FlaskConical size={22} /></div>
        <strong>PolymerLit Extractor</strong>
        <span>正在加载文献抽取工作台…</span>
      </main>
    );
  }

  const navItems = [
    { key: "upload" as const, label: "上传文献", icon: UploadCloud },
    { key: "history" as const, label: "抽取结果", icon: Database },
    { key: "batch" as const, label: "批处理结果", icon: Archive },
    { key: "polyinfo" as const, label: "批次对照", icon: FileSearch },
    { key: "sample" as const, label: "样品详情", icon: Beaker },
  ];

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: "#0066CC",
          colorInfo: "#0066CC",
          colorSuccess: "#178A63",
          colorWarning: "#B66A12",
          colorError: "#C9362B",
          colorText: "#111827",
          colorTextSecondary: "#5F6B7A",
          colorBorder: "#D9E0E8",
          colorBgLayout: "#F2F4F7",
          colorBgContainer: "#FFFFFF",
          controlHeight: 38,
          borderRadius: 8,
          fontSize: 15,
          fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', 'Microsoft YaHei', sans-serif",
        },
        components: {
          Button: { fontWeight: 600 },
          Table: { headerBg: "#F5F7F9", headerColor: "#394555", cellPaddingBlock: 14, cellPaddingInline: 16 },
          Tabs: { itemSelectedColor: "#0066CC", inkBarColor: "#0066CC", titleFontSize: 15 },
          Segmented: { itemSelectedBg: "#FFFFFF", trackBg: "#EDF1F5" },
        },
      }}
    >
      {contextHolder}
      <div className={`tool-shell precision-ui ${collapsed ? "is-collapsed" : ""}`}>
        <aside className="tool-sidebar">
          <div className="tool-brand">
            <div className="brand-symbol"><FlaskConical size={20} /></div>
            {!collapsed && <strong>PolymerLit <span>Extractor</span></strong>}
          </div>
          <nav className="side-nav" aria-label="主导航">
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <button key={item.key} className={view === item.key || (item.key === "history" && ["results", "polymer"].includes(view)) ? "active" : ""} onClick={() => navigate(item.key)} title={item.label}>
                  <Icon size={17} />
                  {!collapsed && <span>{item.label}</span>}
                  {!collapsed && ["results", "sample"].includes(item.key) && !candidate && <i>待生成</i>}
                </button>
              );
            })}
          </nav>
          <div className="side-secondary">
            <button title="设置"><Settings size={17} />{!collapsed && <span>系统设置</span>}</button>
          </div>
        </aside>

        <header className="tool-header">
          <Button type="text" aria-label={collapsed ? "展开侧栏" : "收起侧栏"} icon={collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />} onClick={() => setCollapsed((value) => !value)} />
          <div className="header-breadcrumb">
            <span>文献抽取</span><ChevronRight size={14} />
            <strong>{{ upload: "上传与流水线", history: "网页抽取结果", batch: "离线批处理归档", polyinfo: "批处理与 PoLyInfo 对照", results: "论文聚合物目录", polymer: "聚合物样品列表", sample: "样品性质详情" }[view]}</strong>
          </div>
          <div className="service-state">
            <span className={health ? "online" : "offline"} />
            {health ? "抽取服务在线" : "抽取服务未连接"}
          </div>
          {candidate && ["results", "polymer", "sample"].includes(view) && (
            <Space className="header-actions">
              <Button href={pdfUrl} target="_blank" icon={<FileSearch size={15} />}>原文</Button>
              <Button onClick={downloadJson} icon={<Download size={15} />}>导出数据</Button>
            </Space>
          )}
        </header>

        {candidate && ["results", "polymer", "sample"].includes(view) && candidate.publication.validation_status === "not_validated" && (
          <div className="candidate-banner"><AlertTriangle size={15} /><strong>候选结果尚未完成科学语义校验</strong><span>可用于人工审核，不可直接入库或统计分析。</span>{dataSource === "task" && <Tag color="blue">网页抽取</Tag>}{dataSource === "batch" && <Tag color="purple">离线批处理</Tag>}{dataSource === "sample" && <Tag>内置示例</Tag>}</div>
        )}

        <main className="tool-content">
          {view === "upload" && (
            <UploadPage
              file={selectedFile}
              job={job}
              health={health}
              apiChecked={apiChecked}
              uploading={uploading}
              dmxApiKey={dmxApiKey}
              mineruApiKey={mineruApiKey}
              onFile={setSelectedFile}
              onDmxApiKey={setDmxApiKey}
              onMineruApiKey={setMineruApiKey}
              onStart={startExtraction}
              onRefresh={checkHealth}
              onLoadSample={loadSample}
              onOpenResults={openResults}
            />
          )}
          {view === "history" && (
            <ArchiveResultsPage
              kind="history"
              loading={archiveLoading}
              historyTasks={historyTasks}
              batchResults={[]}
              onRefresh={refreshHistory}
              onOpenHistory={openHistoryTask}
              onOpenBatch={openBatchResult}
            />
          )}
          {view === "batch" && (
            <ArchiveResultsPage
              kind="batch"
              loading={archiveLoading}
              historyTasks={[]}
              batchResults={batchResults}
              onRefresh={refreshBatchResults}
              onOpenHistory={openHistoryTask}
              onOpenBatch={openBatchResult}
            />
          )}
          {view === "polyinfo" && (
            <PolyInfoResultsPage
              loading={archiveLoading}
              rows={polyInfoResults}
              onRefresh={refreshPolyInfoResults}
              onCompare={openPolyInfoComparison}
            />
          )}
          {view === "results" && (
            candidate ? (
              <ResultsPage
                candidate={candidate}
                search={entitySearch}
                filter={entityFilter}
                sourceFileName={dataSource === "task" ? job?.file_name : undefined}
                sourceReferenceNo={dataSource === "batch" ? selectedBatch?.ref_no : job?.source_reference_no || job?.file_name?.replace(/\.pdf$/i, "")}
                sourceLabel={dataSource === "batch" ? "离线批处理归档" : dataSource === "sample" ? "内置示例" : "网页上传任务"}
                onSearch={setEntitySearch}
                onFilter={setEntityFilter}
                onEntity={setSelectedEntity}
                onEvidence={setSelectedEvidence}
                graphPayload={graphPayload}
                onBack={returnToResultList}
                onPolymer={openPolymerPage}
                onSample={openSamplePage}
              />
            ) : <NoResult onUpload={() => setView("upload")} onSample={loadSample} />
          )}
          {view === "polymer" && (
            candidate ? (
              <PolymerPage
                candidate={candidate}
                entityId={selectedPolymerId}
                onBack={() => setView("results")}
                onSample={openSamplePage}
              />
            ) : <NoResult onUpload={() => setView("upload")} onSample={loadSample} />
          )}
          {view === "sample" && (
            candidate ? (
              <SamplePage
                candidate={candidate}
                selectedId={selectedSampleId || candidate.samples[0]?.sample_id}
                onEvidence={setSelectedEvidence}
                onBack={() => setView(selectedPolymerId ? "polymer" : "results")}
              />
            ) : <NoResult onUpload={() => setView("upload")} onSample={loadSample} />
          )}
        </main>

        <nav className="mobile-nav" aria-label="移动端导航">
          {navItems.map((item) => { const Icon = item.icon; return <button key={item.key} className={view === item.key || (item.key === "history" && ["results", "polymer"].includes(view)) ? "active" : ""} onClick={() => navigate(item.key)}><Icon size={18} /><span>{item.label}</span></button>; })}
        </nav>
      </div>

      <EvidenceDrawer evidence={selectedEvidence} pdfUrl={pdfUrl} onClose={() => setSelectedEvidence(null)} />
      <EntityDrawer entity={selectedEntity} evidence={candidate?.evidence || []} onEvidence={setSelectedEvidence} onClose={() => setSelectedEntity(null)} />
      <PolyInfoComparisonDrawer comparison={polyInfoComparison} loading={polyInfoComparisonLoading} onClose={() => setPolyInfoComparison(null)} />
    </ConfigProvider>
  );
}

function PageTitle({ title, description, meta, actions }: { title: string; description: string; meta?: string; actions?: React.ReactNode }) {
  return (
    <div className="page-title-row">
      <div>{meta && <Text className="page-meta">{meta}</Text>}<Title level={2}>{title}</Title><Paragraph>{description}</Paragraph></div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

function UploadPage({ file, job, health, apiChecked, uploading, dmxApiKey, mineruApiKey, onFile, onDmxApiKey, onMineruApiKey, onStart, onRefresh, onLoadSample, onOpenResults }: {
  file: File | null;
  job: ExtractionJob | null;
  health: HealthState | null;
  apiChecked: boolean;
  uploading: boolean;
  dmxApiKey: string;
  mineruApiKey: string;
  onFile: (file: File | null) => void;
  onDmxApiKey: (value: string) => void;
  onMineruApiKey: (value: string) => void;
  onStart: () => void;
  onRefresh: () => void;
  onLoadSample: () => void;
  onOpenResults: () => void;
}) {
  const displayedStages: JobStage[] = stageCatalog.map((stage) => job?.stages.find((item) => item.id === stage.id) || { id: stage.id, status: "pending", artifact: null });
  const keysReady = Boolean(dmxApiKey.trim() && mineruApiKey.trim());
  const secureSubmission = health?.key_submission_allowed !== false;
  const canStart = Boolean(file && health && secureSubmission && keysReady && !uploading && !["queued", "running"].includes(job?.status || ""));
  const fileList: UploadFile[] = file ? [{ uid: "selected-pdf", name: file.name, size: file.size, type: file.type, status: "done" }] : [];

  return (
    <div className="page-stack">
      <PageTitle title="上传高分子论文并运行抽取" description="上传 PDF 后，系统将按照现有 Stage 0–5 流水线提取聚合物、样品、加工过程、性质、测量条件和原文证据。" meta="PDF → SAMPLE-LEVEL DATA" />

      {apiChecked && !health && (
        <Alert className="service-alert" type="warning" showIcon message="本地抽取服务尚未启动" description="运行项目根目录的 start_web_tool.ps1 后刷新服务状态。前端不会伪造抽取进度。" action={<Button onClick={onRefresh}>重新检测</Button>} />
      )}
      {health && !secureSubmission && (
        <Alert className="service-alert" type="warning" showIcon message="当前地址仅供浏览，上传抽取暂未开放" description="API Key 必须通过 HTTPS 传输。请改用系统提供的 HTTPS 地址；请勿在当前 HTTP 地址输入真实密钥。" />
      )}
      <div className="upload-layout">
        <section className="work-panel upload-panel">
          <div className="panel-heading"><div><Title level={4}>上传高分子论文 PDF</Title><Text>单篇任务 · 最大 50 MB</Text></div><Tag color={health ? "success" : "default"}>{health ? "服务可用" : "等待服务"}</Tag></div>
          <div className="api-key-panel">
            <div className="api-key-heading"><ShieldCheck size={17} /><div><strong>本次任务凭据</strong><span>仅在抽取进程内存中使用，任务结束后清除，不写入结果、日志或浏览器存储。</span></div></div>
            <div className="api-key-grid">
              <label htmlFor="dmx-api-key"><span>DMX API Key</span><Input.Password id="dmx-api-key" value={dmxApiKey} onChange={(event) => onDmxApiKey(event.target.value)} autoComplete="new-password" placeholder="输入本次 LLM 调用密钥" /></label>
              <label htmlFor="mineru-api-key"><span>MinerU API Key</span><Input.Password id="mineru-api-key" value={mineruApiKey} onChange={(event) => onMineruApiKey(event.target.value)} autoComplete="new-password" placeholder="输入本次 PDF 解析密钥" /></label>
            </div>
          </div>
          <Dragger
            accept="application/pdf,.pdf"
            multiple={false}
            fileList={fileList}
            showUploadList={false}
            beforeUpload={(next) => { onFile(next); return Upload.LIST_IGNORE; }}
            disabled={["queued", "running"].includes(job?.status || "")}
          >
            <div className="drop-icon"><FileJson size={34} /></div>
            <strong>点击选择或拖拽 PDF 到这里</strong>
            <span>必须是可读取的高分子论文 PDF</span>
            <Button type="primary" icon={<FolderSearch size={15} />}>选择文件</Button>
          </Dragger>

          {file ? (
            <div className="selected-file">
              <div className="pdf-mark">PDF</div>
              <div><strong>{file.name}</strong><span>{formatBytes(file.size)} · 等待提交</span></div>
              {!job || !["queued", "running"].includes(job.status) ? <Button type="text" aria-label="移除文件" icon={<X size={16} />} onClick={() => onFile(null)} /> : <Check size={17} className="success-icon" />}
            </div>
          ) : <div className="file-placeholder">选择文件后，这里会显示真实文件名和大小。</div>}

          <div className="upload-actions">
            <Button type="primary" size="large" loading={uploading} disabled={!canStart} icon={<Play size={16} />} onClick={onStart}>开始抽取</Button>
            <Button size="large" onClick={onLoadSample}>加载已完成示例</Button>
          </div>

          <div className="task-note"><ShieldCheck size={16} /><span>上传文件保存在独立任务目录；请仅使用个人密钥并在任务结束后到服务商控制台核对用量。</span></div>
        </section>

        <section className="work-panel progress-panel">
          <div className="panel-heading"><div><Title level={4}>抽取流水线进度</Title><Text>{job ? `${job.ref_no} · ${job.file_name}` : "提交任务后显示真实阶段状态"}</Text></div>{job && <Tag color={job.status === "complete" ? "success" : job.status === "failed" ? "error" : "processing"}>{job.status === "complete" ? "已完成" : job.status === "failed" ? "失败" : "运行中"}</Tag>}</div>
          <div className="stage-list">
            {stageCatalog.map((stage, index) => {
              const state = displayedStages[index];
              return (
                <div className={`stage-row ${state.status}`} key={stage.id}>
                  <div className="stage-rail"><span>{state.status === "complete" ? <Check size={13} /> : state.status === "running" ? <LoaderCircle size={14} className="spin" /> : state.status === "failed" ? <X size={13} /> : index + 1}</span></div>
                  <div className="stage-copy"><strong>{stage.name} <small>({stage.en})</small></strong><p>{stage.detail}</p></div>
                  <div className="stage-state">{stageStatusLabel(state.status)}{state.artifact && <small>{state.artifact}</small>}</div>
                </div>
              );
            })}
          </div>
          <div className="overall-progress">
            <div><strong>整体进度</strong><span>{job?.progress || 0}%</span></div>
            <Progress percent={job?.progress || 0} showInfo={false} status={job?.status === "failed" ? "exception" : job?.status === "complete" ? "success" : "active"} />
            {job?.error && <Alert type="error" showIcon message="任务未完成" description={job.error} />}
            {job?.result_ready && <Button type="primary" block icon={<Database size={16} />} onClick={onOpenResults}>查看抽取结果</Button>}
          </div>
        </section>
      </div>
    </div>
  );
}

type ArchiveRow = {
  key: string;
  refNo: string;
  title: string;
  doi?: string | null;
  meta: string;
  time: string;
  source: string;
  status: string;
  validation?: string | null;
  stats: ResultStats;
  task?: ExtractionJob;
  batch?: BatchResultSummary;
};

function ArchiveResultsPage({ kind, loading, historyTasks, batchResults, onRefresh, onOpenHistory, onOpenBatch }: {
  kind: "history" | "batch";
  loading: boolean;
  historyTasks: ExtractionJob[];
  batchResults: BatchResultSummary[];
  onRefresh: () => void;
  onOpenHistory: (task: ExtractionJob) => void;
  onOpenBatch: (item: BatchResultSummary) => void;
}) {
  const emptyStats: ResultStats = { polymer_count: 0, sample_count: 0, property_count: 0, process_count: 0, characterization_count: 0, evidence_count: 0 };
  const rows: ArchiveRow[] = kind === "history"
    ? historyTasks.map((task) => ({
        key: task.task_id,
        refNo: task.source_reference_no || task.file_name.replace(/\.pdf$/i, "") || task.ref_no,
        title: displayPaperTitle(task.paper, task.file_name),
        doi: task.paper?.doi,
        meta: displayPaperMeta(task.paper),
        time: formatTaskTime(task.created_at),
        source: "网页上传",
        status: task.status,
        validation: task.validation_status,
        stats: task.stats || emptyStats,
        task,
      }))
    : batchResults.map((item) => ({
        key: item.ref_no,
        refNo: item.ref_no,
        title: displayPaperTitle(item.paper, item.ref_no),
        doi: item.paper?.doi,
        meta: displayPaperMeta(item.paper),
        time: item.result_date || "2026-08-09",
        source: item.source_batch || item.collection_id,
        status: "complete",
        validation: item.validation_status,
        stats: item.stats,
        batch: item,
      }));

  const totals = rows.reduce((sum, row) => ({
    polymer_count: sum.polymer_count + row.stats.polymer_count,
    sample_count: sum.sample_count + row.stats.sample_count,
    property_count: sum.property_count + row.stats.property_count,
    process_count: sum.process_count + row.stats.process_count,
    characterization_count: sum.characterization_count + row.stats.characterization_count,
    evidence_count: sum.evidence_count + row.stats.evidence_count,
  }), emptyStats);

  const columns: ColumnsType<ArchiveRow> = [
    {
      title: "文献",
      key: "paper",
      width: 390,
      render: (_, row) => <div className="archive-paper"><strong>{row.title}</strong><span>{row.refNo}{row.doi ? ` · DOI ${row.doi}` : " · DOI 未识别"}</span><small>{row.meta}</small></div>,
    },
    {
      title: "关系摘要",
      key: "chain",
      width: 315,
      render: (_, row) => <div className="archive-chain"><span>论文</span><ChevronRight size={13} /><b>{row.stats.polymer_count} 聚合物</b><ChevronRight size={13} /><b>{row.stats.sample_count} 样品</b><ChevronRight size={13} /><b>{row.stats.property_count} 性质</b></div>,
    },
    {
      title: kind === "history" ? "上传时间" : "批次",
      key: "source",
      width: 165,
      render: (_, row) => <div className="archive-source"><strong>{kind === "history" ? row.time : row.source}</strong><span>{kind === "history" ? row.source : row.time}</span></div>,
    },
    {
      title: "状态",
      key: "status",
      width: 120,
      render: (_, row) => <Space size={4} direction="vertical"><Tag color={row.status === "complete" ? "success" : row.status === "failed" ? "error" : "processing"}>{row.status === "complete" ? "已完成" : row.status === "failed" ? "失败" : "运行中"}</Tag>{row.validation === "not_validated" && <Tag color="warning">待校验</Tag>}</Space>,
    },
    {
      title: "操作",
      key: "action",
      width: 120,
      fixed: "right",
      render: (_, row) => <Button type="primary" disabled={row.status !== "complete"} onClick={() => row.task ? onOpenHistory(row.task) : row.batch && onOpenBatch(row.batch)}>打开关系</Button>,
    },
  ];

  return <div className="page-stack archive-page">
    <PageTitle
      title={kind === "history" ? "抽取结果" : "离线批处理结果"}
      description={kind === "history" ? "按上传时间从新到旧展示网页任务。打开任一文献后，可按文献 → 聚合物 → 样品 → 性质逐层查看。" : "独立展示 2026-08-09 Stage 4 Preview 重跑并重新发布的 20 篇候选结果；这些记录不是在网页端生成，不会混入网页历史。"}
      meta={kind === "history" ? "WEB EXTRACTION HISTORY" : "OFFLINE BATCH · DEMO20 PREVIEW 2026-08-09"}
      actions={<Button icon={<RefreshCw size={15} />} loading={loading} onClick={onRefresh}>刷新列表</Button>}
    />
    <Alert
      className="archive-source-alert"
      type={kind === "history" ? "info" : "warning"}
      showIcon
      message={kind === "history" ? "数据源：web_runtime/tasks" : "数据源：batch_results/demo20_preview_20260809"}
      description={kind === "history" ? "这里不会展示离线 demo20 批处理记录。运行中和失败任务仍保留，便于追踪抽取历史。" : "这 20 篇已完成 Stage 4 Preview 修复重跑和 Candidate 对账，但仍属于 Preview 数据，仅供审核和对比。"}
    />
    <section className="archive-metrics">
      <Metric icon={<FileSearch size={19} />} label="文献" value={rows.length} tone="blue" />
      <Metric icon={<Boxes size={19} />} label="聚合物实体" value={totals.polymer_count} tone="violet" />
      <Metric icon={<Beaker size={19} />} label="具体样品" value={totals.sample_count} tone="cyan" />
      <Metric icon={<Gauge size={19} />} label="性质观测" value={totals.property_count} tone="orange" />
    </section>
    <section className="work-panel archive-table-panel">
      <div className="panel-heading"><div><Title level={4}>{kind === "history" ? "网页任务记录" : "Demo20 Preview 文献记录"}</Title><Text>每行显示文献及其关系链规模，点击后进入完整关系、图谱和样品详情。</Text></div><Tag color={kind === "history" ? "blue" : "purple"}>{rows.length} 篇</Tag></div>
      <Table rowKey="key" loading={loading} columns={columns} dataSource={rows} pagination={{ pageSize: 10, showSizeChanger: false }} scroll={{ x: 1110 }} locale={{ emptyText: <Empty description={kind === "history" ? "还没有网页抽取记录" : "未发现 demo20 批处理结果"} /> }} />
    </section>
  </div>;
}

function PolyInfoResultsPage({ loading, rows, onRefresh, onCompare }: {
  loading: boolean;
  rows: PolyInfoSummary[];
  onRefresh: () => void;
  onCompare: (refNo: string) => void;
}) {
  const [search, setSearch] = useState("");
  const query = search.trim().toLowerCase();
  const filtered = rows.filter((item) => !query || [
    item.ref_no,
    item.reference.doi,
    item.reference.journal,
    ...item.polymer_names,
  ].filter(Boolean).join(" ").toLowerCase().includes(query)).sort((left, right) =>
    Number(right.has_batch_result) - Number(left.has_batch_result) || left.ref_no.localeCompare(right.ref_no),
  );
  const totals = rows.reduce((sum, item) => ({
    polymers: sum.polymers + item.stats.polymer_count,
    samples: sum.samples + item.stats.sample_count,
    properties: sum.properties + item.stats.property_count,
    matched: sum.matched + (item.has_batch_result ? 1 : 0),
  }), { polymers: 0, samples: 0, properties: 0, matched: 0 });

  const columns: ColumnsType<PolyInfoSummary> = [
    {
      title: "文献与来源",
      key: "paper",
      width: 330,
      render: (_, item) => <div className="polyinfo-paper-cell"><strong>{item.ref_no}</strong><span>{item.reference.journal || "期刊未记录"} · {item.reference.year || "年份未记录"}</span><small>{item.reference.doi || "无 DOI"}</small></div>,
    },
    {
      title: "PoLyInfo 聚合物",
      key: "polymers",
      render: (_, item) => <div className="polyinfo-polymer-cell"><strong>{item.polymer_names[0] || "名称未记录"}</strong>{item.polymer_name_count > 1 && <span>另有 {item.polymer_name_count - 1} 个规范名称</span>}<small>{item.stats.polymer_count} PID · {item.stats.structure_count} 个结构图</small></div>,
    },
    { title: "样品", key: "samples", width: 86, align: "right", render: (_, item) => <b className="numeric-cell">{item.stats.sample_count}</b> },
    { title: "性质值", key: "properties", width: 96, align: "right", render: (_, item) => <b className="numeric-cell">{item.stats.property_count}</b> },
    { title: "工艺字段", key: "processes", width: 96, align: "right", render: (_, item) => <b className="numeric-cell">{item.stats.process_count}</b> },
    { title: "来源组", dataIndex: "group", key: "group", width: 88, render: (value) => <Tag color={value === "有doi" ? "blue" : "default"}>{value}</Tag> },
    { title: "最新批处理", key: "matched", width: 118, render: (_, item) => item.has_batch_result ? <Tag color="success">可直接对照</Tag> : <Tag>本批次无结果</Tag> },
    {
      title: "操作",
      key: "action",
      width: 210,
      render: (_, item) => <Space size={7}><Button type={item.has_batch_result ? "primary" : "default"} icon={<GitBranch size={15} />} onClick={() => onCompare(item.ref_no)}>{item.has_batch_result ? "查看批次差异" : "查看原始记录"}</Button>{item.has_pdf && <Tooltip title="打开该目录中的论文 PDF"><Button aria-label="打开 PoLyInfo 对应论文" href={`${API_BASE}/api/polyinfo-results/${item.ref_no}/pdf`} target="_blank" icon={<FileSearch size={15} />} /></Tooltip>}</Space>,
    },
  ];

  return <div className="page-stack polyinfo-results-page">
    <PageTitle title="最新批处理与 PoLyInfo 对照" description="按 reference_no 连接 demo20_preview_20260809 与本地真实 PoLyInfo 样品 JSON，比较聚合物、样品、性质、工艺和证据覆盖。" meta="PREVIEW EXTRACTION · POLYINFO REFERENCE" actions={<Button icon={<RefreshCw size={15} />} loading={loading} onClick={onRefresh}>刷新目录</Button>} />
    <Alert className="polyinfo-source-alert" type="info" showIcon message="对照源：最新 Preview 批处理 ↔ 本地 PoLyInfo 数据" description="20 篇批处理文献中有 17 篇找到同 reference_no 的 PoLyInfo 记录。PoLyInfo 本地 JSON 没有页码、BBox 与原文片段，因此证据链数量按 0 统计。" />
    <section className="metric-strip polyinfo-metrics">
      <Metric icon={<FileSearch size={19} />} label="PoLyInfo 文献" value={rows.length} tone="blue" />
      <Metric icon={<Boxes size={19} />} label="聚合物 PID" value={totals.polymers} tone="violet" />
      <Metric icon={<Beaker size={19} />} label="样品记录" value={totals.samples} tone="cyan" />
      <Metric icon={<Gauge size={19} />} label="性质观测" value={totals.properties} tone="orange" />
      <Metric icon={<GitBranch size={19} />} label="可配对批次" value={totals.matched} tone="green" />
    </section>
    <section className="work-panel polyinfo-table-panel">
      <div className="polyinfo-table-toolbar"><div><strong>真实 PoLyInfo 文献记录</strong><span>当前显示 {filtered.length} / {rows.length} 篇；每篇文献可包含多个样品 JSON。</span></div><Input value={search} onChange={(event) => setSearch(event.target.value)} prefix={<Search size={15} />} placeholder="搜索 reference_no、DOI、期刊或聚合物" allowClear /></div>
      <Table rowKey="ref_no" loading={loading} columns={columns} dataSource={filtered} pagination={{ pageSize: 12, showSizeChanger: false }} scroll={{ x: 1280 }} rowClassName={(item) => item.has_batch_result ? "polyinfo-linked-row" : ""} locale={{ emptyText: <Empty description="没有读取到 PoLyInfo 原始记录" /> }} />
    </section>
  </div>;
}

function ResultsPage({ candidate, graphPayload, sourceFileName, sourceReferenceNo, sourceLabel, search, filter, onSearch, onFilter, onEntity, onEvidence, onSample, onPolymer, onBack }: {
  candidate: CandidateData;
  graphPayload: GraphPayload | null;
  sourceFileName?: string;
  sourceReferenceNo?: string | null;
  sourceLabel: string;
  search: string;
  filter: string;
  onSearch: (value: string) => void;
  onFilter: (value: string) => void;
  onEntity: (entity: PolymerEntity) => void;
  onEvidence: (evidence: Evidence) => void;
  onSample: (id: string) => void;
  onPolymer: (id: string) => void;
  onBack: () => void;
}) {
  const evidenceMap = useMemo(() => new Map(candidate.evidence.map((item) => [item.evidence_id, item])), [candidate]);
  const entities = candidate.polymer_entities.filter((entity) => {
    const query = search.trim().toLowerCase();
    const matches = !query || [entity.polymer_name, ...(entity.source_names || [])].join(" ").toLowerCase().includes(query);
    const sampleCount = candidate.samples.filter((sample) => sample.refers_to_entity === entity.entity_id).length;
    return matches && (filter === "all" || (filter === "sample" && sampleCount > 0) || (filter === "low" && (entity.confidence?.score || 0) < 0.8));
  });

  const columns: ColumnsType<PolymerEntity> = [
    { title: "聚合物名称", dataIndex: "polymer_name", key: "name", width: 300, render: (value, record) => <button className="name-link" onClick={() => onEntity(record)}><strong>{value}</strong><span>{record.entity_id}</span></button> },
    { title: "简称与原文名称", dataIndex: "source_names", key: "aliases", render: (names?: string[]) => <div className="tag-list">{(names || []).slice(0, 3).map((name) => <Tag key={name}>{name}</Tag>)}{(names || []).length > 3 && <Tag>+{(names || []).length - 3}</Tag>}</div> },
    { title: "样品数量", key: "samples", width: 105, render: (_, record) => { const samples = candidate.samples.filter((sample) => sample.refers_to_entity === record.entity_id); return samples.length ? <Button type="link" onClick={() => onSample(samples[0].sample_id)}>{samples.length}</Button> : <Text type="secondary">0</Text>; } },
    { title: "类型", key: "type", width: 120, render: (_, record) => candidate.samples.some((sample) => sample.refers_to_entity === record.entity_id && sample.sample_kind === "processed_material") ? <Tag color="blue">复合/加工材料</Tag> : <Tag>聚合物实体</Tag> },
    { title: "置信度", key: "confidence", width: 95, render: (_, record) => confidenceTag(record.confidence?.score) },
    { title: "操作", key: "action", width: 90, render: (_, record) => <Tooltip title="查看原文证据"><Button aria-label="查看实体证据" icon={<Link2 size={15} />} onClick={() => { const item = record.evidence_ids?.map((id) => evidenceMap.get(id)).find(Boolean); if (item) onEvidence(item); }} /></Tooltip> },
  ];

  return (
    <div className="page-stack">
      <PageTitle title="论文关系化抽取结果" description="沿论文 → 聚合物 → 样品 → 性质逐层浏览；所有关系均来自候选 JSON 中的对象 ID。" meta={`${sourceLabel} · ${displayPaperMeta(candidate.paper)}`} actions={<Button icon={<ArrowLeft size={15} />} onClick={onBack}>返回结果列表</Button>} />

      <section className="work-panel paper-summary">
        <div className="paper-main"><Text>文献 · {sourceLabel}</Text><Title level={4}>{displayPaperTitle(candidate.paper, sourceReferenceNo || "未识别题名")}</Title><div className="paper-fields"><span><b>作者</b>{displayPaperAuthors(candidate.paper.authors)}</span><span><b>DOI</b>{candidate.paper.doi || "未识别"}</span><span><b>来源编号</b>{sourceReferenceNo || candidate.paper.ref_no}</span>{sourceFileName && <span><b>上传文件</b>{sourceFileName}</span>}</div></div>
        <div className="paper-badge"><FileSearch size={28} /><span>{sourceLabel}</span><strong>{candidate.paper.year || "--"}</strong></div>
      </section>

      <section className="metric-strip">
        <Metric icon={<Boxes size={19} />} label="聚合物实体" value={candidate.polymer_entities.length} tone="blue" />
        <Metric icon={<Beaker size={19} />} label="具体样品" value={candidate.samples.length} tone="violet" />
        <Metric icon={<Gauge size={19} />} label="性质观测" value={candidate.property_observations.length} tone="cyan" />
        <Metric icon={<GitBranch size={19} />} label="加工步骤" value={candidate.process_steps.length} tone="orange" />
        <Metric icon={<FileSearch size={19} />} label="原文证据" value={candidate.evidence.length} tone="green" />
      </section>

      <section className="work-panel result-browser">
        <Tabs
          defaultActiveKey="hierarchy"
          items={[
            {
              key: "hierarchy",
              label: <span className="mode-tab"><Workflow size={15} />聚合物目录</span>,
              children: <PolymerDirectory candidate={candidate} entities={entities} search={search} filter={filter} onSearch={onSearch} onFilter={onFilter} onEntity={onEntity} onPolymer={onPolymer} />,
            },
            {
              key: "graph",
              label: <span className="mode-tab"><Network size={15} />知识图谱</span>,
              children: <KnowledgeGraph candidate={candidate} payload={graphPayload} onEntity={onEntity} onEvidence={onEvidence} onSample={onSample} />,
            },
            {
              key: "tables",
              label: <span className="mode-tab"><TableProperties size={15} />数据表</span>,
              children: <div className="flat-data-view">
                <div className="panel-heading responsive"><div><Title level={4}>识别到的聚合物</Title><Text>保留传统表格视图，便于检索、排序和批量审核</Text></div><Space wrap><Input value={search} onChange={(event) => onSearch(event.target.value)} prefix={<Search size={15} />} placeholder="搜索名称或缩写" allowClear /><Select value={filter} onChange={onFilter} options={[{ value: "all", label: "全部实体" }, { value: "sample", label: "仅有关联样品" }, { value: "low", label: "低置信度" }]} /></Space></div>
                <Table rowKey="entity_id" columns={columns} dataSource={entities} pagination={{ pageSize: 7 }} scroll={{ x: 920 }} />
                <div className="table-section-heading"><div><Title level={4}>样品清单</Title><Text>点击样品进入完整详情</Text></div><Tag color="blue">{candidate.samples.length} 个样品</Tag></div>
                <Table rowKey="sample_id" pagination={false} scroll={{ x: 820 }} dataSource={candidate.samples} columns={[
                  { title: "样品", key: "sample", render: (_, item) => <div className="primary-cell"><strong>{sampleDisplayName(item)}</strong><span>{item.sample_id}</span></div> },
                  { title: "聚合物/材料", dataIndex: "polymer_name", key: "polymer" },
                  { title: "样品类型", dataIndex: "sample_kind", key: "kind", render: sampleKindLabel },
                  { title: "状态", dataIndex: "state_description", key: "state", render: (value) => value || <Text type="secondary">原文未明确</Text> },
                  { title: "性质数", key: "properties", width: 85, render: (_, item) => candidate.property_observations.filter((property) => property.sample_id === item.sample_id).length },
                  { title: "操作", key: "action", width: 90, render: (_, item) => <Button type="link" onClick={() => onSample(item.sample_id)}>查看详情</Button> },
                ]} />
              </div>,
            },
          ]}
        />
      </section>

      {candidate.warnings.length > 0 && (
        <section className="work-panel warning-panel"><div className="panel-heading"><div><Title level={4}>待人工复核</Title><Text>警告保持可见，不把候选结果包装成已验证数据</Text></div><Tag color="warning">{candidate.warnings.length} 项</Tag></div><div className="warning-grid">{candidate.warnings.slice(0, 6).map((warning, index) => <div key={`${warning.code}-${index}`}><AlertTriangle size={15} /><span><strong>{warningLabels[warning.code] || warning.code}</strong><small>{warning.stage}</small></span></div>)}</div></section>
      )}
    </div>
  );
}

function PolymerDirectory({ candidate, entities, search, filter, onSearch, onFilter, onEntity, onPolymer }: {
  candidate: CandidateData;
  entities: PolymerEntity[];
  search: string;
  filter: string;
  onSearch: (value: string) => void;
  onFilter: (value: string) => void;
  onEntity: (entity: PolymerEntity) => void;
  onPolymer: (id: string) => void;
}) {
  return <div className="polymer-directory-view">
    <div className="polymer-directory-toolbar"><div><strong>识别到 {entities.length} 个聚合物</strong><span>PID 由规范名称稳定生成；结构和 CU formula 只在有可靠依据时展示。</span></div><Space wrap><Input value={search} onChange={(event) => onSearch(event.target.value)} prefix={<Search size={15} />} placeholder="搜索聚合物" allowClear /><Select value={filter} onChange={onFilter} options={[{ value: "all", label: "全部实体" }, { value: "sample", label: "仅有关联样品" }, { value: "low", label: "低置信度" }]} /></Space></div>
    {entities.length ? <div className="polymer-result-list">{entities.map((entity, index) => {
      const samples = candidate.samples.filter((sample) => sample.refers_to_entity === entity.entity_id);
      const repeatUnit = repeatUnitFor(entity);
      return <article className="polymer-result-card" key={entity.entity_id}>
        <div className="polymer-result-heading"><button onClick={() => onPolymer(entity.entity_id)}><b>{index + 1}.</b> {entity.polymer_name}</button><Space size={5}>{confidenceTag(entity.confidence?.score)}<Tooltip title="查看实体归一与原文证据"><Button aria-label="查看聚合物证据" icon={<Link2 size={14} />} onClick={() => onEntity(entity)} /></Tooltip></Space></div>
        <div className="polymer-result-meta"><span><b>PID</b>{systemPid(entity)}</span><span><b>CU formula</b>{repeatUnit.formula || "待补充"}</span><button onClick={() => onPolymer(entity.entity_id)}>{samples.length} samples <ChevronRight size={14} /></button><Tag>{polymerTypeLabel(entity.polymer_type, entity.polymer_name)}</Tag></div>
        <button className="polymer-structure-button" onClick={() => onPolymer(entity.entity_id)} aria-label={`查看 ${entity.polymer_name} 的样品`}><PolymerStructure entity={entity} compact /></button>
      </article>;
    })}</div> : <Empty description="没有符合筛选条件的聚合物" />}
  </div>;
}

function PolymerPage({ candidate, entityId, onBack, onSample }: { candidate: CandidateData; entityId: string; onBack: () => void; onSample: (id: string) => void }) {
  const entity = candidate.polymer_entities.find((item) => item.entity_id === entityId);
  if (!entity) return <div className="page-stack"><Button className="standalone-back" icon={<ArrowLeft size={15} />} onClick={onBack}>返回聚合物目录</Button><Empty description="没有找到该聚合物实体" /></div>;
  const samples = candidate.samples.filter((sample) => sample.refers_to_entity === entity.entity_id);
  const repeatUnit = repeatUnitFor(entity);
  const entityRecord = entity as unknown as Record<string, unknown>;
  const columns: ColumnsType<CandidateData["samples"][number]> = [
    { title: "NO.", key: "no", width: 70, render: (_, __, index) => index + 1 },
    { title: "SAMPLE ID", dataIndex: "sample_id", key: "sample", width: 145, render: (value) => <Button type="link" className="sample-id-link" onClick={() => onSample(value)}>{value}</Button> },
    { title: "MATERIAL TYPE", key: "material", width: 170, render: (_, sample) => sampleKindLabel(sample.sample_kind) },
    { title: "ADDITIVES", key: "additives", width: 150, render: (_, sample) => { const additives = (sample as unknown as Record<string, unknown>).additives; return Array.isArray(additives) && additives.length ? additives.join(", ") : "-"; } },
    { title: "POLYMER TYPE", key: "polymerType", width: 170, render: () => polymerTypeLabel(entity.polymer_type, entity.polymer_name) },
    { title: "PROPERTY", key: "property", render: (_, sample) => { const properties = candidate.property_observations.filter((item) => item.sample_id === sample.sample_id); return properties.length ? <button className="sample-property-preview" onClick={() => onSample(sample.sample_id)}>{properties.slice(0, 5).map((item) => <span key={item.property_id}>{item.property_name_raw} <b>{item.value_raw} {item.unit_normalized || item.unit_raw || ""}</b></span>)}{properties.length > 5 && <small>另有 {properties.length - 5} 条性质</small>}</button> : <Text type="secondary">暂无性质记录</Text>; } },
  ];

  return <div className="page-stack polymer-page">
    <PageTitle title={`Sample List (${entity.polymer_name})`} description={`${systemPid(entity)} · ${polymerTypeLabel(entity.polymer_type, entity.polymer_name)}`} meta="POLYMER ENTITY" actions={<Button icon={<ArrowLeft size={15} />} onClick={onBack}>返回聚合物目录</Button>} />
    <section className="work-panel polymer-identity-panel">
      <div className="polymer-structure-large"><PolymerStructure entity={entity} /></div>
      <div className="polymer-identity-data"><span><b>PID</b>{systemPid(entity)}</span><span><b>CU formula</b>{repeatUnit.formula || "待补充"}</span><span><b>Sample count</b>{samples.length}</span><span><b>Polymer type</b>{polymerTypeLabel(entity.polymer_type, entity.polymer_name)}</span><span className="wide"><b>Source names</b>{entity.source_names?.join("；") || "未报告"}</span><span className="wide"><b>Structure status</b>{repeatUnit.definition ? "名称词典匹配的重复单元示意" : String(entityRecord.representation_status || "待专家补充")}</span></div>
    </section>
    <section className="work-panel polymer-sample-table"><div className="polymer-table-heading"><div><strong>样品列表</strong><span>Number of data points: {samples.length}</span></div><Tag color="blue">PID = {systemPid(entity)}</Tag></div><Table rowKey="sample_id" columns={columns} dataSource={samples} pagination={{ pageSize: 10, hideOnSinglePage: true }} scroll={{ x: 1040 }} locale={{ emptyText: <Empty description="该聚合物尚未绑定样品" /> }} /></section>
  </div>;
}

function buildGraphPayload(candidate: CandidateData): GraphPayload {
  const paperId = `paper:${candidate.paper.ref_no}`;
  const nodes: GraphNodePayload[] = [{ id: paperId, type: "paper", label: candidate.paper.title, data: candidate.paper as unknown as Record<string, unknown> }];
  const edges: GraphPayload["edges"] = [];
  candidate.polymer_entities.forEach((entity) => {
    nodes.push({ id: entity.entity_id, type: "polymer", label: entity.polymer_name, data: entity as unknown as Record<string, unknown> });
    edges.push({ id: `${paperId}:contains:${entity.entity_id}`, source: paperId, target: entity.entity_id, type: "contains_polymer", label: "识别" });
  });
  candidate.samples.forEach((sample) => {
    nodes.push({ id: sample.sample_id, type: "sample", label: sampleDisplayName(sample), data: sample as unknown as Record<string, unknown> });
    edges.push({ id: `${sample.refers_to_entity}:sample:${sample.sample_id}`, source: sample.refers_to_entity, target: sample.sample_id, type: "has_sample", label: "对应样品" });
  });
  candidate.process_steps.forEach((step) => {
    nodes.push({ id: step.step_id, type: "process", label: step.process_type, data: step as unknown as Record<string, unknown> });
    step.input_sample_ids.forEach((id) => edges.push({ id: `${id}:input:${step.step_id}`, source: id, target: step.step_id, type: "process_input", label: "输入" }));
    step.output_sample_ids.forEach((id) => edges.push({ id: `${step.step_id}:output:${id}`, source: step.step_id, target: id, type: "process_output", label: "生成" }));
  });
  candidate.property_observations.forEach((property) => {
    const unit = property.unit_normalized || property.unit_raw || "";
    nodes.push({ id: property.property_id, type: "property", label: `${property.property_name_raw}: ${property.value_raw} ${unit}`.trim(), data: property as unknown as Record<string, unknown> });
    edges.push({ id: `${property.sample_id}:property:${property.property_id}`, source: property.sample_id, target: property.property_id, type: "has_property", label: "测得" });
  });
  candidate.characterizations.forEach((item) => {
    nodes.push({ id: item.characterization_id, type: "characterization", label: item.method_normalized || item.method_raw, data: item as unknown as Record<string, unknown> });
    item.sample_ids?.forEach((id) => edges.push({ id: `${id}:characterization:${item.characterization_id}`, source: id, target: item.characterization_id, type: "characterized_by", label: "表征" }));
  });
  const nodeCounts = nodes.reduce<Record<string, number>>((counts, node) => ({ ...counts, [node.type]: (counts[node.type] || 0) + 1 }), {});
  return { nodes, edges, stats: { node_counts: nodeCounts, edge_count: edges.length } };
}

type FlowNodeData = { kind: GraphNodePayload["type"]; source: GraphNodePayload; title: string; subtitle: string; label: React.ReactNode };
type FlowNode = Node<FlowNodeData>;

function KnowledgeGraph({ candidate, payload, onEntity, onEvidence, onSample }: { candidate: CandidateData; payload: GraphPayload | null; onEntity: (entity: PolymerEntity) => void; onEvidence: (evidence: Evidence) => void; onSample: (id: string) => void }) {
  const [scope, setScope] = useState<"core" | "all">("core");
  const graph = payload || buildGraphPayload(candidate);
  const evidenceMap = useMemo(() => new Map(candidate.evidence.map((item) => [item.evidence_id, item])), [candidate]);
  const linkedPolymerIds = new Set(graph.edges.filter((edge) => edge.type === "has_sample").map((edge) => edge.source));
  const visibleSourceNodes = scope === "all" ? graph.nodes : graph.nodes.filter((node) => node.type !== "polymer" || linkedPolymerIds.has(node.id));
  const visibleIds = new Set(visibleSourceNodes.map((node) => node.id));
  const activeEdges = graph.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target));
  const typeLabels: Record<GraphNodePayload["type"], string> = { paper: "SOURCE PAPER", polymer: "POLYMER ENTITY", sample: "SAMPLE STATE", process: "PROCESS EVENT", property: "PROPERTY", characterization: "CHARACTERIZATION" };
  const palette = {
    paper: { x: 20, color: "#0066CC", bg: "#FFFFFF" },
    polymer: { x: 285, color: "#7B5AA6", bg: "#FFFFFF" },
    sample: { x: 550, color: "#008C95", bg: "#FFFFFF" },
    process: { x: 815, color: "#D27A16", bg: "#FFFFFF" },
    property: { x: 1080, color: "#178A63", bg: "#FFFFFF" },
    characterization: { x: 1345, color: "#66788A", bg: "#FFFFFF" },
  } as const;

  const gap = 112;
  const positionY = new Map<string, number>();
  const nodesOf = (type: GraphNodePayload["type"]) => visibleSourceNodes.filter((node) => node.type === type);
  const placeColumn = (items: GraphNodePayload[], desired: (item: GraphNodePayload, index: number) => number) => {
    const ranked = items.map((item, index) => ({ item, desired: desired(item, index) })).sort((a, b) => a.desired - b.desired || a.item.label.localeCompare(b.item.label));
    let previous = -gap;
    ranked.forEach(({ item, desired: target }) => {
      const y = Math.max(24, target, previous + gap);
      positionY.set(item.id, y);
      previous = y;
    });
  };
  const average = (values: number[], fallback: number) => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : fallback;

  const polymerNodes = nodesOf("polymer");
  const polymerRank = new Map(polymerNodes.sort((a, b) => a.label.localeCompare(b.label)).map((node, index) => [node.id, index]));
  const sampleNodes = nodesOf("sample").sort((a, b) => {
    const parentA = activeEdges.find((edge) => edge.type === "has_sample" && edge.target === a.id)?.source || "";
    const parentB = activeEdges.find((edge) => edge.type === "has_sample" && edge.target === b.id)?.source || "";
    return (polymerRank.get(parentA) ?? 999) - (polymerRank.get(parentB) ?? 999) || a.label.localeCompare(b.label);
  });
  placeColumn(sampleNodes, (_, index) => 24 + index * gap);
  placeColumn(polymerNodes, (node, index) => {
    const childY = activeEdges.filter((edge) => edge.type === "has_sample" && edge.source === node.id).map((edge) => positionY.get(edge.target)).filter((value): value is number => value !== undefined);
    return average(childY, 24 + index * gap);
  });
  const paperNodes = nodesOf("paper");
  placeColumn(paperNodes, () => average(polymerNodes.map((node) => positionY.get(node.id)).filter((value): value is number => value !== undefined), 140));
  const processNodes = nodesOf("process");
  placeColumn(processNodes, (node, index) => {
    const linkedY = activeEdges.filter((edge) => (edge.source === node.id || edge.target === node.id) && ["process_input", "process_output"].includes(edge.type)).map((edge) => positionY.get(edge.source === node.id ? edge.target : edge.source)).filter((value): value is number => value !== undefined);
    return average(linkedY, 24 + index * gap);
  });
  const propertyNodes = nodesOf("property");
  placeColumn(propertyNodes, (node, index) => {
    const linkedY = activeEdges.filter((edge) => edge.target === node.id).map((edge) => positionY.get(edge.source)).filter((value): value is number => value !== undefined);
    return average(linkedY, 24 + index * gap);
  });
  const characterizationNodes = nodesOf("characterization");
  placeColumn(characterizationNodes, (node, index) => {
    const linkedY = activeEdges.filter((edge) => edge.target === node.id).map((edge) => positionY.get(edge.source)).filter((value): value is number => value !== undefined);
    return average(linkedY, 24 + index * gap);
  });

  const nodes: FlowNode[] = visibleSourceNodes.map((source) => {
    const style = palette[source.type];
    return {
      id: source.id,
      position: { x: style.x, y: positionY.get(source.id) || 24 },
      data: { kind: source.type, source, title: source.label, subtitle: source.id, label: <div className="graph-node-copy"><span className="graph-node-type"><i style={{ background: style.color }} />{typeLabels[source.type]}</span><strong>{source.label}</strong><small>{source.id}</small></div> },
      style: { width: source.type === "paper" ? 240 : 208, minHeight: 84, border: "1px solid #D5DDE6", borderLeft: `4px solid ${style.color}`, borderRadius: 8, background: style.bg, color: "#172033", padding: "12px 13px 12px 14px", fontSize: 13, boxShadow: "0 8px 22px rgba(16,24,40,.08)" },
      ariaLabel: `${source.type}: ${source.label}`,
    };
  });
  const edgeColors: Record<string, string> = { contains_polymer: "#4F85BB", has_sample: "#8874A8", process_input: "#C18443", process_output: "#C18443", has_property: "#4E8F74", characterized_by: "#7A8998" };
  const edges: Edge[] = activeEdges.map((edge) => {
    const color = edgeColors[edge.type] || "#8794a6";
    return { id: edge.id, source: edge.source, target: edge.target, label: activeEdges.length <= 42 ? edge.label : undefined, type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color }, style: { stroke: color, strokeWidth: 1.7, opacity: .82 }, labelStyle: { fill: "#526071", fontSize: 10, fontWeight: 650 }, labelBgStyle: { fill: "#ffffff", fillOpacity: .96 }, labelBgPadding: [5, 4], labelBgBorderRadius: 4, interactionWidth: 18 };
  });
  const handleNodeClick: NodeMouseHandler<FlowNode> = (_, node) => {
    const source = node.data.source;
    if (source.type === "sample") return onSample(source.id);
    if (source.type === "polymer") {
      const entity = candidate.polymer_entities.find((item) => item.entity_id === source.id);
      if (entity) onEntity(entity);
      return;
    }
    const evidenceIds = source.data.evidence_ids;
    if (Array.isArray(evidenceIds)) {
      const item = evidenceIds.map((id) => evidenceMap.get(String(id))).find(Boolean);
      if (item) onEvidence(item);
    }
  };

  return <div className="graph-view">
    <div className="graph-toolbar"><div><strong>样品中心实验知识图谱</strong><span>从文献来源到聚合物、样品状态、工艺事件和观测结果；节点位置按真实关系自动对齐</span></div><Segmented value={scope} onChange={(value) => setScope(value as "core" | "all")} options={[{ label: "关系主干", value: "core" }, { label: "全部实体", value: "all" }]} /></div>
    <div className="graph-legend">{Object.entries(palette).map(([key, value]) => <span key={key}><i style={{ background: value.color }} />{{ paper: "论文", polymer: "聚合物", sample: "样品状态", process: "工艺事件", property: "性质观测", characterization: "表征" }[key as keyof typeof palette]}</span>)}<b>{nodes.length} 节点 · {edges.length} 关系</b></div>
    {!candidate.property_observations.length && <Alert className="graph-alert" type="warning" showIcon message="本次抽取没有生成性质节点" description="图谱仍完整展示聚合物、样品、工艺和表征关系；性质阶段已标记为待重跑或人工复核。" />}
    <div className="graph-stage-headings"><span>文献来源</span><span>聚合物实体</span><span>样品状态</span><span>工艺事件</span><span>性质观测</span><span>表征方法</span></div>
    <div className="graph-canvas"><ReactFlow nodes={nodes} edges={edges} onNodeClick={handleNodeClick} fitView fitViewOptions={{ padding: 0.06, maxZoom: 1.08 }} minZoom={0.24} maxZoom={1.7} nodesDraggable nodesConnectable={false} elementsSelectable onlyRenderVisibleElements proOptions={{ hideAttribution: true }}><MiniMap pannable zoomable maskColor="rgba(247,249,251,.78)" nodeStrokeWidth={2} nodeColor={(node) => palette[(node.data as FlowNodeData).kind].color} /><Controls showInteractive={false} /><Background color="#DDE3EA" gap={30} size={1} /></ReactFlow></div>
  </div>;
}

function SamplePage({ candidate, selectedId, onEvidence, onBack }: {
  candidate: CandidateData;
  selectedId?: string;
  onEvidence: (evidence: Evidence) => void;
  onBack: () => void;
}) {
  const sample = candidate.samples.find((item) => item.sample_id === selectedId) || candidate.samples[0];
  if (!sample) return <div className="page-stack"><Button className="standalone-back" icon={<ArrowLeft size={15} />} onClick={onBack}>返回样品列表</Button><Empty description="当前结果中没有样品" /></div>;
  const entity = candidate.polymer_entities.find((item) => item.entity_id === sample.refers_to_entity);
  const properties = candidate.property_observations.filter((item) => item.sample_id === sample.sample_id);
  const evidenceMap = new Map(candidate.evidence.map((item) => [item.evidence_id, item]));
  const entityPid = entity ? systemPid(entity) : "待归一";

  const propertyColumns: ColumnsType<PropertyObservation> = [
    { title: "性质名称", dataIndex: "property_name_raw", key: "name", render: (value, record) => <div className="primary-cell"><strong>{value}</strong><span>{record.property_code || "尚未映射性质编码"}</span></div> },
    { title: "测试方法", key: "method", width: 160, render: (_, record) => { const item = record as unknown as Record<string, unknown>; const method = item.method_normalized || item.method_raw || item.test_method; return method ? String(method) : <Text type="secondary">未建立方法绑定</Text>; } },
    { title: "测试条件", key: "condition", width: 210, render: (_, record) => <span className="condition-copy">{measurementConditionText(candidate, record)}</span> },
    { title: "数值", key: "value", width: 120, render: (_, record) => <strong className="property-value">{record.value_raw}</strong> },
    { title: "单位", key: "unit", width: 90, render: (_, record) => record.unit_normalized || record.unit_raw || "-" },
    { title: "来源", dataIndex: "source_type", key: "source", width: 90, render: (value) => value || "-" },
    { title: "置信度", key: "confidence", width: 95, render: (_, record) => confidenceTag(record.confidence?.score) },
    { title: "原文证据", key: "evidence", width: 95, render: (_, record) => { const item = record.evidence_ids?.map((id) => evidenceMap.get(id)).find(Boolean); return <Tooltip title={item ? "查看该性质的原文证据" : "当前记录未绑定可定位证据"}><Button aria-label="查看性质证据" disabled={!item} icon={<Link2 size={15} />} onClick={() => item && onEvidence(item)} /></Tooltip>; } },
  ];

  return (
    <div className="page-stack sample-property-page">
      <PageTitle title={`Property Data (${sampleDisplayName(sample)})`} description={`${sample.sample_id} · ${entity?.polymer_name || sample.polymer_name}`} meta="SAMPLE PROPERTY" actions={<Button icon={<ArrowLeft size={15} />} onClick={onBack}>返回样品列表</Button>} />

      <section className="work-panel sample-property-identity">
        <div className="sample-avatar"><Beaker size={23} /></div>
        <div className="sample-property-title"><strong>{sampleDisplayName(sample)}</strong><span>{sample.polymer_name}</span></div>
        <div className="sample-identity-fields">
          <span><b>SAMPLE ID</b>{sample.sample_id}</span>
          <span><b>PID</b>{entityPid}</span>
          <span><b>MATERIAL TYPE</b>{sampleKindLabel(sample.sample_kind)}</span>
          <span><b>POLYMER TYPE</b>{polymerTypeLabel(entity?.polymer_type, entity?.polymer_name || sample.polymer_name)}</span>
          <span><b>STATE</b>{sample.state_description || "原文未明确报告"}</span>
          <span><b>PROPERTY COUNT</b>{properties.length}</span>
        </div>
      </section>

      <section className="work-panel sample-property-table">
        <div className="sample-property-heading"><div><strong>性质数据</strong><span>每条性质保留数值、单位、测量语境、置信度与原文证据</span></div><Tag color="blue">{properties.length} records</Tag></div>
        {properties.length ? <Table rowKey="property_id" columns={propertyColumns} dataSource={properties} pagination={{ pageSize: 10, hideOnSinglePage: true }} scroll={{ x: 1080 }} /> : <Empty description="本次性质阶段未生成可用观测" />}
      </section>
    </div>
  );
}

function Metric({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: number; tone: string }) {
  return <div className="metric-item"><div className={`metric-icon ${tone}`}>{icon}</div><div><span>{label}</span><strong>{value}</strong></div></div>;
}

function NoResult({ onUpload, onSample }: { onUpload: () => void; onSample: () => void }) {
  return <div className="empty-page"><div className="empty-illustration"><Database size={34} /></div><Title level={3}>尚未生成抽取结果</Title><Paragraph>先上传一篇高分子论文并等待流水线完成。也可以加载内置示例查看页面结构。</Paragraph><Space><Button type="primary" icon={<UploadCloud size={16} />} onClick={onUpload}>上传论文</Button><Button onClick={onSample}>加载示例</Button></Space></div>;
}

function EvidenceVisual({ evidence, pdfUrl }: { evidence: Evidence; pdfUrl: string }) {
  const [pageAspect, setPageAspect] = useState(1.414);
  const [imageFailed, setImageFailed] = useState(false);
  const page = evidence.page ?? 0;
  const pageImageUrl = `${pdfUrl}/pages/${page}`;
  const sourceWidth = 1000;
  const sourceHeight = sourceWidth * pageAspect;
  const values = Array.isArray(evidence.bbox) ? evidence.bbox.map(Number) : [];
  const hasBox = values.length === 4 && values.every(Number.isFinite) && values[2] > values[0] && values[3] > values[1];
  const x0 = hasBox ? Math.max(0, Math.min(sourceWidth, values[0])) : 0;
  const y0 = hasBox ? Math.max(0, Math.min(sourceHeight, values[1])) : 0;
  const x1 = hasBox ? Math.max(x0 + 1, Math.min(sourceWidth, values[2])) : sourceWidth;
  const y1 = hasBox ? Math.max(y0 + 1, Math.min(sourceHeight, values[3])) : sourceHeight;
  const boxWidth = x1 - x0;
  const boxHeight = y1 - y0;
  const boxStyle: React.CSSProperties = {
    left: `${(x0 / sourceWidth) * 100}%`,
    top: `${(y0 / sourceHeight) * 100}%`,
    width: `${(boxWidth / sourceWidth) * 100}%`,
    height: `${(boxHeight / sourceHeight) * 100}%`,
  };
  const cropImageStyle: React.CSSProperties = {
    width: `${(sourceWidth / boxWidth) * 100}%`,
    left: `${(-x0 / boxWidth) * 100}%`,
    top: `${(-y0 / boxHeight) * 100}%`,
  };

  if (imageFailed) return <Alert type="warning" showIcon message="证据页图像暂不可用" description="仍可通过下方按钮直接打开 PDF 对应页核对证据。" />;

  return <section className="evidence-visual-panel">
    <div className="evidence-visual-heading"><div><strong>原文定位</strong><span>红框为抽取记录保存的 bbox 坐标</span></div><Tag color="red">Page {page + 1}</Tag></div>
    <div className="evidence-page-preview">
      <img src={pageImageUrl} alt={`原文第 ${page + 1} 页证据定位`} onLoad={(event) => setPageAspect(event.currentTarget.naturalHeight / event.currentTarget.naturalWidth)} onError={() => setImageFailed(true)} />
      {hasBox && <i className="evidence-bbox" style={boxStyle}><span>bbox</span></i>}
    </div>
    {hasBox && <div className="evidence-crop-section"><div><strong>证据区域放大</strong><span>{values.join(", ")}</span></div><div className="evidence-crop-frame" style={{ aspectRatio: `${boxWidth} / ${boxHeight}` }}><img src={pageImageUrl} alt="根据 bbox 裁剪的原文证据区域" style={cropImageStyle} /><i /></div></div>}
  </section>;
}

function extractionPropertyValue(item?: PropertyObservation | null) {
  if (!item) return "-";
  return `${item.value_raw ?? "-"} ${item.unit_normalized || item.unit_raw || ""}`.trim();
}

function alignmentStatusTag(status: PolyInfoComparison["property_alignment"][number]["status"]) {
  const config = {
    matched: { color: "success", label: "数值一致" },
    value_diff: { color: "error", label: "同名但值不同" },
    polyinfo_only: { color: "warning", label: "仅 PoLyInfo" },
    extraction_only: { color: "blue", label: "仅最新批处理" },
  }[status];
  return <Tag color={config.color}>{config.label}</Tag>;
}

function PolyInfoComparisonDrawer({ comparison, loading, onClose }: { comparison: PolyInfoComparison | null; loading: boolean; onClose: () => void }) {
  const metricColumns: ColumnsType<PolyInfoComparison["metrics"][number]> = [
    { title: "比较维度", dataIndex: "label", key: "label", width: 160, render: (value) => <strong>{value}</strong> },
    { title: "PoLyInfo", dataIndex: "polyinfo", key: "polyinfo", width: 100, align: "right", render: (value) => <b className="numeric-cell polyinfo-number">{value}</b> },
    { title: "最新批处理", dataIndex: "extraction", key: "extraction", width: 118, align: "right", render: (value) => <b className="numeric-cell extraction-number">{value}</b> },
    { title: "差值", key: "delta", width: 90, align: "right", render: (_, item) => { const delta = item.extraction - item.polyinfo; return <Tag color={delta === 0 ? "success" : delta > 0 ? "blue" : "warning"}>{delta > 0 ? `+${delta}` : delta}</Tag>; } },
    { title: "解释", dataIndex: "interpretation", key: "interpretation" },
  ];
  const alignmentColumns: ColumnsType<PolyInfoComparison["property_alignment"][number]> = [
    { title: "判定", dataIndex: "status", key: "status", width: 126, render: alignmentStatusTag },
    { title: "统一性质名", dataIndex: "canonical_name", key: "name", width: 210, render: (value) => <strong>{value}</strong> },
    { title: "PoLyInfo 样品", key: "piSample", width: 150, render: (_, item) => item.polyinfo?.sample_id || "-" },
    { title: "PoLyInfo 值", key: "piValue", width: 150, render: (_, item) => item.polyinfo ? <span className="comparison-value polyinfo-number">{item.polyinfo.value} {item.polyinfo.unit || ""}</span> : "-" },
    { title: "批处理样品", key: "webSample", width: 110, render: (_, item) => item.extraction?.sample_id || "-" },
    { title: "批处理值", key: "webValue", width: 150, render: (_, item) => item.extraction ? <span className="comparison-value extraction-number">{extractionPropertyValue(item.extraction)}</span> : "-" },
    { title: "方法与条件", key: "context", render: (_, item) => <div className="comparison-context"><span>{item.polyinfo?.method || ((item.extraction as unknown as Record<string, unknown> | null)?.determination_method_raw as string) || "方法未记录"}</span><small>{item.polyinfo?.condition || "条件见批处理证据记录或未报告"}</small></div> },
  ];
  const polyInfoSampleColumns: ColumnsType<PolyInfoComparison["polyinfo"]["samples"][number]> = [
    { title: "SAMPLE ID", dataIndex: "sample_id", key: "sample", width: 190 },
    { title: "PID", dataIndex: "polymer_id", key: "pid", width: 120 },
    { title: "材料类型", dataIndex: "material_type", key: "material", render: (value: string[]) => value?.join("；") || "-" },
    { title: "聚合物类型", dataIndex: "polymer_type", key: "type", width: 130 },
    { title: "性质", dataIndex: "property_count", key: "properties", width: 80, align: "right" },
    { title: "工艺字段", dataIndex: "process_count", key: "process", width: 90, align: "right" },
  ];
  const extractionSampleColumns: ColumnsType<CandidateData["samples"][number]> = [
    { title: "SAMPLE ID", dataIndex: "sample_id", key: "sample", width: 120 },
    { title: "绑定实体", dataIndex: "refers_to_entity", key: "entity", width: 120 },
    { title: "样品名称", key: "name", render: (_, item) => sampleDisplayName(item) },
    { title: "样品类型", dataIndex: "sample_kind", key: "kind", width: 140, render: sampleKindLabel },
    { title: "状态", dataIndex: "state_description", key: "state", render: (value) => value || "原文未明确报告" },
  ];
  const processColumns: ColumnsType<PolyInfoComparison["polyinfo"]["processes"][number]> = [
    { title: "SAMPLE ID", dataIndex: "sample_id", key: "sample", width: 190 },
    { title: "字段", dataIndex: "kind", key: "kind", width: 170 },
    { title: "PoLyInfo 内容", dataIndex: "value", key: "value" },
  ];

  const overview = comparison && <div className="comparison-tab">
    <div className="comparison-heading"><div><Text className="page-meta">{comparison.ref_no}</Text><Title level={4}>{comparison.polyinfo.reference.journal || "PoLyInfo 文献记录"}</Title><Paragraph>{comparison.polyinfo.reference.doi || "无 DOI"} · {comparison.polyinfo.reference.year || "年份未记录"}</Paragraph></div><Space wrap><Tag color="blue">PoLyInfo: {comparison.polyinfo.group}</Tag>{comparison.extraction ? <Tag color="success">匹配批次 {comparison.extraction.collection_id}</Tag> : <Tag color="warning">本批次无结果</Tag>}</Space></div>
    {!comparison.extraction && <Alert type="warning" showIcon message="最新批处理没有可比较结果" description="该 reference_no 不在 demo20_preview_20260809 中；这里只展示 PoLyInfo 原始记录。" />}
    {comparison.extraction && <Alert type="info" showIcon message={comparison.message} description="样品数量和实体数量受建模层级影响，不能直接当作准确率；逐性质表才用于判断具体缺失、额外抽取或数值冲突。" />}
    {comparison.alignment_stats && <div className="alignment-summary"><span className="matched"><b>{comparison.alignment_stats.matched || 0}</b>数值一致</span><span className="different"><b>{comparison.alignment_stats.value_diff || 0}</b>同名值不同</span><span className="pi-only"><b>{comparison.alignment_stats.polyinfo_only || 0}</b>仅 PoLyInfo</span><span className="web-only"><b>{comparison.alignment_stats.extraction_only || 0}</b>仅最新批处理</span></div>}
    <Table rowKey="key" className="comparison-metric-table" columns={metricColumns} dataSource={comparison.metrics} pagination={false} size="middle" />
    <div className="comparison-notes"><strong>本页应怎样解读</strong><p>PoLyInfo 是样品记录参考，不自动等于全文 gold truth。批处理多出的内容可能是有效补充，也可能是错绑；PoLyInfo 缺少证据链，因此所有争议项最终仍需回到 PDF 和 bbox 证据裁决。</p></div>
  </div>;

  const identity = comparison && <div className="comparison-tab">
    <div className="source-identity-grid">
      <section><div className="comparison-section-title"><strong>PoLyInfo 聚合物</strong><span>{comparison.polyinfo.polymers.length} PID</span></div>{comparison.polyinfo.polymers.map((polymer) => <article className="polyinfo-identity-card" key={polymer.polymer_id}>{polymer.structure_image ? <img src={polymer.structure_image} alt={`${polymer.polymer_id} 重复单元结构`} /> : <div className="polyinfo-structure-empty"><FlaskConical size={22} />无结构图</div>}<div><b>{polymer.polymer_id}</b><strong>{polymer.polymer_names.join("；") || "名称未记录"}</strong><span>{polymer.cu_formula || "CU formula 未记录"} · {polymer.polymer_type || "类型未记录"}</span><small>{polymer.sample_ids.length} samples</small></div></article>)}</section>
      <section><div className="comparison-section-title"><strong>最新批处理聚合物实体</strong><span>{comparison.extraction?.polymer_entities.length || 0} entities</span></div>{comparison.extraction?.polymer_entities.map((entity) => <article className="extraction-identity-card" key={entity.entity_id}><div className="entity-mark"><Boxes size={20} /></div><div><b>{entity.entity_id}</b><strong>{entity.polymer_name}</strong><span>{entity.source_names?.slice(0, 3).join("；") || "无原文别名"}</span><small>{Math.round((entity.confidence?.score || 0) * 100)}% confidence</small></div></article>) || <Empty description="本批次无抽取实体" />}</section>
    </div>
    <div className="comparison-section-title table-title"><strong>PoLyInfo 样品记录</strong><span>每个 JSON 对应一个样品记录</span></div><Table rowKey="sample_id" columns={polyInfoSampleColumns} dataSource={comparison.polyinfo.samples} pagination={{ pageSize: 8, hideOnSinglePage: true }} scroll={{ x: 900 }} />
    <div className="comparison-section-title table-title"><strong>最新批处理样品状态</strong><span>样品可表示合成批次、加工态和状态变化</span></div><Table rowKey="sample_id" columns={extractionSampleColumns} dataSource={comparison.extraction?.samples || []} pagination={{ pageSize: 8, hideOnSinglePage: true }} scroll={{ x: 880 }} />
  </div>;

  const properties = comparison && <div className="comparison-tab"><Alert type="warning" showIcon message="一致表示名称、单位换算和数值相符，不代表样品绑定已自动验证" description="同一篇论文可能同时包含多个聚合物和状态；样品归属仍需结合原文证据检查。" /><Table rowKey={(item) => `${item.status}:${item.polyinfo?.id || item.extraction?.property_id}`} className="property-alignment-table" columns={alignmentColumns} dataSource={comparison.property_alignment} pagination={{ pageSize: 12, showSizeChanger: false }} scroll={{ x: 1260 }} /></div>;

  const rawRecords = comparison && <div className="comparison-tab"><div className="comparison-section-title"><strong>PoLyInfo 工艺与制样字段</strong><span>这些是原始字段值，不代表已恢复为有顺序的过程事件图</span></div><Table rowKey={(item, index) => `${item.sample_id}:${item.kind}:${index}`} columns={processColumns} dataSource={comparison.polyinfo.processes} pagination={{ pageSize: 10, hideOnSinglePage: true }} /><div className="comparison-section-title table-title"><strong>PoLyInfo 全部性质记录</strong><span>{comparison.polyinfo.properties.length} 条数值观测</span></div><Table rowKey="id" columns={[{ title: "SAMPLE ID", dataIndex: "sample_id", key: "sample", width: 190 }, { title: "性质", dataIndex: "name", key: "name", width: 240 }, { title: "值", key: "value", width: 140, render: (_, item: PolyInfoProperty) => `${item.value} ${item.unit || ""}` }, { title: "方法", dataIndex: "method", key: "method", width: 160, render: (value) => value || "-" }, { title: "条件", dataIndex: "condition", key: "condition", render: (value) => value || "-" }]} dataSource={comparison.polyinfo.properties} pagination={{ pageSize: 12, showSizeChanger: false }} scroll={{ x: 1050 }} /></div>;

  return <Drawer className="polyinfo-comparison-drawer" title="最新批处理与 PoLyInfo 对照" width={1180} open={loading || Boolean(comparison)} onClose={onClose}>{loading && !comparison ? <div className="comparison-loading"><LoaderCircle size={30} className="spin" /><strong>正在解析真实 PoLyInfo 样品记录并计算差异</strong></div> : comparison && <Tabs defaultActiveKey="overview" items={[{ key: "overview", label: "对照总览", children: overview }, { key: "identity", label: "聚合物与样品", children: identity }, { key: "properties", label: `性质逐项 (${comparison.property_alignment.length})`, children: properties }, { key: "raw", label: "PoLyInfo 原始记录", children: rawRecords }]} />}</Drawer>;
}

function EvidenceDrawer({ evidence, pdfUrl, onClose }: { evidence: Evidence | null; pdfUrl: string; onClose: () => void }) {
  return (
    <Drawer title="原文证据" width={820} open={Boolean(evidence)} onClose={onClose}>
      {evidence && <div className="evidence-drawer"><div className="evidence-location"><Tag color="blue">第 {(evidence.page ?? 0) + 1} 页</Tag><Tag>{evidence.source_type || "text"}</Tag><Text type="secondary">{evidence.block_id}</Text></div><EvidenceVisual key={evidence.evidence_id} evidence={evidence} pdfUrl={pdfUrl} /><blockquote>{evidence.source_sentence || "未保存可展示的原文片段。"}</blockquote><Descriptions column={1} bordered size="small"><Descriptions.Item label="证据 ID">{evidence.evidence_id}</Descriptions.Item><Descriptions.Item label="来源阶段">{evidence.source_stage}</Descriptions.Item><Descriptions.Item label="对象 ID">{evidence.object_id}</Descriptions.Item><Descriptions.Item label="版面坐标">{evidence.bbox?.join(", ") || "未记录"}</Descriptions.Item></Descriptions><Button block type="primary" href={`${pdfUrl}#page=${(evidence.page ?? 0) + 1}`} target="_blank" icon={<FileSearch size={16} />}>在原文中打开本页</Button></div>}
    </Drawer>
  );
}

function EntityDrawer({ entity, evidence, onEvidence, onClose }: { entity: PolymerEntity | null; evidence: Evidence[]; onEvidence: (item: Evidence) => void; onClose: () => void }) {
  return (
    <Drawer title="聚合物实体详情" width={520} open={Boolean(entity)} onClose={onClose}>
      {entity && <div className="entity-drawer"><Title level={4}>{entity.polymer_name}</Title><Space wrap><Tag color="warning">需专家复核</Tag>{confidenceTag(entity.confidence?.score)}</Space><Descriptions column={1} bordered size="small"><Descriptions.Item label="实体 ID">{entity.entity_id}</Descriptions.Item><Descriptions.Item label="关联指称">{entity.resolved_from_mentions?.length || 0} 条</Descriptions.Item><Descriptions.Item label="结构特征">{entity.structural_features?.length ? entity.structural_features.join("；") : "尚未抽取"}</Descriptions.Item></Descriptions><div><Text strong>原文名称与别名</Text><div className="tag-list drawer-tags">{entity.source_names?.map((name) => <Tag key={name}>{name}</Tag>)}</div></div><Alert type="warning" showIcon message="统一实体仍需人工确认" description="名称相近不等于结构、组成或样品状态完全相同。" /><Button block icon={<Link2 size={15} />} onClick={() => { const item = entity.evidence_ids?.map((id) => evidence.find((entry) => entry.evidence_id === id)).find(Boolean); if (item) onEvidence(item); }}>查看实体证据</Button></div>}
    </Drawer>
  );
}
