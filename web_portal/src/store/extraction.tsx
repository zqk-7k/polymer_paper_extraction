
import { message } from "antd";
import { useNavigate } from "react-router-dom";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import sampleCandidate from "../data/reference_no_0101911_candidate.json";
import type {
  BatchCollectionSummary,
  BatchResultSummary,
  CandidateData,
  Evidence,
  ExtractionJob,
  GraphPayload,
  HealthState,
  PolyInfoComparison,
  PolyInfoSummary,
  PolymerEntity,
} from "../types";
import { API_BASE } from "../types";
import { batchPdfUrl } from "../evidence-urls.mjs";

type DataSource = "task" | "batch" | "sample" | null;

type ExtractionContextValue = {
  mounted: boolean;
  collapsed: boolean;
  setCollapsed: (v: boolean | ((p: boolean) => boolean)) => void;
  contextHolder: React.ReactNode;
  selectedFile: File | null;
  setSelectedFile: (f: File | null) => void;
  dmxApiKey: string;
  setDmxApiKey: (v: string) => void;
  mineruApiKey: string;
  setMineruApiKey: (v: string) => void;
  job: ExtractionJob | null;
  health: HealthState | null;
  apiChecked: boolean;
  uploading: boolean;
  candidate: CandidateData | null;
  graphPayload: GraphPayload | null;
  dataSource: DataSource;
  selectedBatch: BatchResultSummary | null;
  historyTasks: ExtractionJob[];
  batchResults: BatchResultSummary[];
  batchCollections: BatchCollectionSummary[];
  selectedBatchCollectionId: string;
  polyInfoResults: PolyInfoSummary[];
  polyInfoComparison: PolyInfoComparison | null;
  polyInfoComparisonLoading: boolean;
  archiveLoading: boolean;
  selectedPolymerId: string;
  selectedSampleId: string;
  entitySearch: string;
  setEntitySearch: (v: string) => void;
  entityFilter: string;
  setEntityFilter: (v: string) => void;
  selectedEvidence: Evidence | null;
  setSelectedEvidence: (e: Evidence | null) => void;
  selectedEntity: PolymerEntity | null;
  setSelectedEntity: (e: PolymerEntity | null) => void;
  setPolyInfoComparison: (c: PolyInfoComparison | null) => void;
  pdfUrl: string;
  downloadJson: () => void;
  checkHealth: () => Promise<void>;
  loadTaskResult: (task: ExtractionJob) => Promise<void>;
  refreshHistory: () => Promise<void>;
  refreshBatchResults: (collectionId?: string) => Promise<void>;
  refreshBatchCollections: () => Promise<BatchCollectionSummary[]>;
  refreshPolyInfoResults: (collectionId?: string) => Promise<void>;
  openPolyInfoComparison: (refNo: string, collectionId?: string) => Promise<void>;
  startExtraction: () => Promise<void>;
  loadSample: () => void;
  openResults: () => void;
  selectBatchCollection: (collectionId: string) => void;
  ensureBatchPage: (kind: "batch" | "polyinfo") => void;
  openHistoryTask: (task: ExtractionJob) => Promise<void>;
  openBatchResult: (item: BatchResultSummary) => Promise<void>;
  returnToResultList: () => void;
  openPolymerPage: (entityId: string) => void;
  openSamplePage: (sampleId: string) => void;
};

const ExtractionContext = createContext<ExtractionContextValue | null>(null);

export function useExtraction() {
  const ctx = useContext(ExtractionContext);
  if (!ctx) throw new Error("useExtraction must be used inside ExtractionProvider");
  return ctx;
}

const STORAGE_KEY = "polyextract-web-state-v1";

type PersistedState = {
  candidate: CandidateData | null;
  graphPayload: GraphPayload | null;
  dataSource: DataSource;
  selectedBatch: BatchResultSummary | null;
  selectedPolymerId: string;
  selectedSampleId: string;
  job: ExtractionJob | null;
};

function readPersistedState(): PersistedState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as PersistedState;
  } catch {
    return null;
  }
}

export function ExtractionProvider({ children }: { children: React.ReactNode }) {
  const router = useNavigate();
  const [persisted] = useState<PersistedState | null>(() => readPersistedState());
  const [mounted, setMounted] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dmxApiKey, setDmxApiKey] = useState("");
  const [mineruApiKey, setMineruApiKey] = useState("");
  const [job, setJob] = useState<ExtractionJob | null>(() => persisted?.job ?? null);
  const [health, setHealth] = useState<HealthState | null>(null);
  const [apiChecked, setApiChecked] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [candidate, setCandidate] = useState<CandidateData | null>(() => persisted?.candidate ?? null);
  const [graphPayload, setGraphPayload] = useState<GraphPayload | null>(() => persisted?.graphPayload ?? null);
  const [dataSource, setDataSource] = useState<DataSource>(() => persisted?.dataSource ?? null);
  const [selectedBatch, setSelectedBatch] = useState<BatchResultSummary | null>(() => persisted?.selectedBatch ?? null);
  const [historyTasks, setHistoryTasks] = useState<ExtractionJob[]>([]);
  const [batchResults, setBatchResults] = useState<BatchResultSummary[]>([]);
  const [batchCollections, setBatchCollections] = useState<BatchCollectionSummary[]>([]);
  const [selectedBatchCollectionId, setSelectedBatchCollectionId] = useState("");
  const [polyInfoResults, setPolyInfoResults] = useState<PolyInfoSummary[]>([]);
  const [polyInfoComparison, setPolyInfoComparison] = useState<PolyInfoComparison | null>(null);
  const [polyInfoComparisonLoading, setPolyInfoComparisonLoading] = useState(false);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const archiveLoadingCount = useRef(0);
  const beginArchiveLoading = useCallback(() => {
    archiveLoadingCount.current += 1;
    setArchiveLoading(true);
  }, []);
  const endArchiveLoading = useCallback(() => {
    archiveLoadingCount.current = Math.max(0, archiveLoadingCount.current - 1);
    if (archiveLoadingCount.current === 0) setArchiveLoading(false);
  }, []);
  const [selectedPolymerId, setSelectedPolymerId] = useState(() => persisted?.selectedPolymerId ?? "");
  const [selectedSampleId, setSelectedSampleId] = useState(() => persisted?.selectedSampleId ?? "");
  const [entitySearch, setEntitySearch] = useState("");
  const [entityFilter, setEntityFilter] = useState("all");
  const [selectedEvidence, setSelectedEvidenceState] = useState<Evidence | null>(null);
  const [selectedEntity, setSelectedEntityState] = useState<PolymerEntity | null>(null);
  const setSelectedEvidence = useCallback((e: Evidence | null) => {
    if (e) setSelectedEntityState(null);
    setSelectedEvidenceState(e);
  }, []);
  const setSelectedEntity = useCallback((e: PolymerEntity | null) => {
    if (e) setSelectedEvidenceState(null);
    setSelectedEntityState(e);
  }, []);
  const [messageApi, contextHolder] = message.useMessage();

  useEffect(() => {
    const timer = window.setTimeout(() => setMounted(true), 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    try {
      const snapshot: PersistedState = { candidate, graphPayload, dataSource, selectedBatch, selectedPolymerId, selectedSampleId, job };
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
    } catch {
      // sessionStorage 可能不可用或超限，忽略即可，页面状态仍保留在内存中。
    }
  }, [candidate, graphPayload, dataSource, selectedBatch, selectedPolymerId, selectedSampleId, job]);

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
    const data = (await response.json()) as CandidateData;
    setCandidate(data);
    setGraphPayload(graphResponse.ok ? ((await graphResponse.json()) as GraphPayload) : null);
    setDataSource("task");
    setSelectedBatch(null);
    setSelectedPolymerId("");
    setSelectedSampleId(data.samples[0]?.sample_id || "");
  }, []);

  const refreshHistory = useCallback(async () => {
    beginArchiveLoading();
    try {
      const response = await fetch(`${API_BASE}/api/tasks?limit=100`);
      if (!response.ok) throw new Error("历史任务读取失败");
      setHistoryTasks((await response.json()) as ExtractionJob[]);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "历史任务读取失败");
    } finally {
      endArchiveLoading();
    }
  }, [messageApi, beginArchiveLoading, endArchiveLoading]);

  const refreshBatchResults = useCallback(
    async (collectionId = "") => {
      beginArchiveLoading();
      try {
        const query = collectionId ? `?collection=${encodeURIComponent(collectionId)}` : "";
        const response = await fetch(`${API_BASE}/api/batch-results${query}`);
        if (!response.ok) throw new Error("批处理结果读取失败");
        setBatchResults((await response.json()) as BatchResultSummary[]);
      } catch (error) {
        messageApi.error(error instanceof Error ? error.message : "批处理结果读取失败");
      } finally {
        endArchiveLoading();
      }
    },
    [messageApi, beginArchiveLoading, endArchiveLoading],
  );

  const refreshBatchCollections = useCallback(async () => {
    beginArchiveLoading();
    try {
      const response = await fetch(`${API_BASE}/api/batch-collections`);
      if (!response.ok) throw new Error("批次质量摘要读取失败");
      const collections = (await response.json()) as BatchCollectionSummary[];
      setBatchCollections(collections);
      return collections;
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "批次质量摘要读取失败");
    } finally {
      endArchiveLoading();
    }
    return [] as BatchCollectionSummary[];
  }, [messageApi, beginArchiveLoading, endArchiveLoading]);

  const refreshPolyInfoResults = useCallback(
    async (collectionId = "") => {
      beginArchiveLoading();
      try {
        const query = collectionId ? `?collection=${encodeURIComponent(collectionId)}` : "";
        const response = await fetch(`${API_BASE}/api/polyinfo-results${query}`);
        if (!response.ok) throw new Error("PoLyInfo 原始数据读取失败");
        setPolyInfoResults((await response.json()) as PolyInfoSummary[]);
      } catch (error) {
        messageApi.error(error instanceof Error ? error.message : "PoLyInfo 原始数据读取失败");
      } finally {
        endArchiveLoading();
      }
    },
    [messageApi, beginArchiveLoading, endArchiveLoading],
  );

  const openPolyInfoComparison = useCallback(
    async (refNo: string, collectionId?: string) => {
      setPolyInfoComparisonLoading(true);
      setPolyInfoComparison(null);
      try {
        const query = collectionId ? `?collection=${encodeURIComponent(collectionId)}` : "";
        const response = await fetch(`${API_BASE}/api/polyinfo-results/${refNo}/comparison${query}`);
        if (!response.ok) throw new Error("PoLyInfo 对照结果读取失败");
        setPolyInfoComparison((await response.json()) as PolyInfoComparison);
      } catch (error) {
        messageApi.error(error instanceof Error ? error.message : "PoLyInfo 对照结果读取失败");
      } finally {
        setPolyInfoComparisonLoading(false);
      }
    },
    [messageApi],
  );

  useEffect(() => {
    if (!mounted || !health || job || candidate) return;
    const restoreLatestTask = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/tasks?limit=1`);
        if (!response.ok) return;
        const tasks = (await response.json()) as ExtractionJob[];
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
        const next = (await response.json()) as ExtractionJob;
        setJob(next);
        if (next.result_ready) await loadTaskResult(next);
      } catch {
        // A temporary polling failure should not overwrite the last real state.
      }
    }, 2000);
    return () => window.clearInterval(poll);
  }, [job, loadTaskResult]);

  const startExtraction = useCallback(async () => {
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
  }, [selectedFile, dmxApiKey, mineruApiKey, messageApi]);

  const loadSample = useCallback(() => {
    const data = sampleCandidate as CandidateData;
    setCandidate(data);
    setGraphPayload(null);
    setDataSource("sample");
    setSelectedBatch(null);
    setSelectedPolymerId(data.samples[0]?.refers_to_entity || "");
    setSelectedSampleId(data.samples[0]?.sample_id || "");
    setJob(null);
    router("/results");
    messageApi.info("已加载内置示例；该结果不代表新上传任务");
  }, [router, messageApi]);

  const openResults = useCallback(() => {
    router("/history");
    void refreshHistory();
  }, [router, refreshHistory]);

  const selectBatchCollection = useCallback(
    (collectionId: string) => {
      setSelectedBatchCollectionId(collectionId);
      void refreshBatchResults(collectionId);
      void refreshPolyInfoResults(collectionId);
    },
    [refreshBatchResults, refreshPolyInfoResults],
  );

  const ensureBatchPage = useCallback(
    (kind: "batch" | "polyinfo") => {
      void (async () => {
        const collections = await refreshBatchCollections();
        const preferred =
          collections.find((item) => item.collection_id === selectedBatchCollectionId) ||
          collections.find((item) => item.collection_kind === "review") ||
          collections.find((item) => item.is_active) ||
          collections[0];
        const collectionId = preferred?.collection_id || "";
        setSelectedBatchCollectionId(collectionId);
        await Promise.all([
          refreshBatchResults(collectionId),
          kind === "polyinfo" ? refreshPolyInfoResults(collectionId) : Promise.resolve(),
        ]);
      })();
    },
    [refreshBatchCollections, refreshBatchResults, refreshPolyInfoResults, selectedBatchCollectionId],
  );

  const openHistoryTask = useCallback(
    async (task: ExtractionJob) => {
      if (!task.result_ready) {
        setJob(task);
        router("/upload");
        messageApi.info(task.status === "failed" ? "该任务执行失败，请在流水线页查看原因" : "该任务尚未完成，已切换到流水线进度");
        return;
      }
      beginArchiveLoading();
      try {
        setJob(task);
        await loadTaskResult(task);
        router("/results");
      } catch {
        messageApi.error("历史抽取结果读取失败");
      } finally {
        endArchiveLoading();
      }
    },
    [router, loadTaskResult, messageApi, beginArchiveLoading, endArchiveLoading],
  );

  const openBatchResult = useCallback(
    async (item: BatchResultSummary) => {
      beginArchiveLoading();
      try {
        const [response, graphResponse] = await Promise.all([
          fetch(`${API_BASE}${item.result_url}`),
          fetch(`${API_BASE}${item.graph_url}`),
        ]);
        if (!response.ok) throw new Error("批处理候选结果不可读取");
        const data = (await response.json()) as CandidateData;
        setCandidate(data);
        setGraphPayload(graphResponse.ok ? ((await graphResponse.json()) as GraphPayload) : null);
        setDataSource("batch");
        setSelectedBatch(item);
        setSelectedPolymerId("");
        setSelectedSampleId(data.samples[0]?.sample_id || "");
        setJob(null);
        router("/results");
      } catch (error) {
        messageApi.error(error instanceof Error ? error.message : "批处理候选结果读取失败");
      } finally {
        endArchiveLoading();
      }
    },
    [router, messageApi, beginArchiveLoading, endArchiveLoading],
  );

  const returnToResultList = useCallback(() => {
    if (dataSource === "batch") {
      router("/batch");
      void refreshBatchResults();
      return;
    }
    if (dataSource === "sample") {
      router("/upload");
      return;
    }
    router("/history");
    void refreshHistory();
  }, [dataSource, router, refreshBatchResults, refreshHistory]);

  const openPolymerPage = useCallback(
    (entityId: string) => {
      setSelectedPolymerId(entityId);
      setSelectedSampleId("");
      router("/polymer");
    },
    [router],
  );

  const openSamplePage = useCallback(
    (sampleId: string) => {
      const sample = candidate?.samples.find((item) => item.sample_id === sampleId);
      if (sample?.refers_to_entity) setSelectedPolymerId(sample.refers_to_entity);
      setSelectedSampleId(sampleId);
      router("/sample");
    },
    [router, candidate],
  );

  const pdfUrl =
    dataSource === "task" && job
      ? `${API_BASE}/api/tasks/${job.task_id}/pdf`
      : dataSource === "batch" && selectedBatch
        ? batchPdfUrl(API_BASE, selectedBatch)
        : `${API_BASE}/api/source-pdfs/reference_no_0101911/pdf`;

  const downloadJson = useCallback(() => {
    if (!candidate) return;
    const blob = new Blob([JSON.stringify(candidate, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${candidate.paper.ref_no}_candidate.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [candidate]);

  const value = useMemo<ExtractionContextValue>(
    () => ({
      mounted,
      collapsed,
      setCollapsed,
      contextHolder,
      selectedFile,
      setSelectedFile,
      dmxApiKey,
      setDmxApiKey,
      mineruApiKey,
      setMineruApiKey,
      job,
      health,
      apiChecked,
      uploading,
      candidate,
      graphPayload,
      dataSource,
      selectedBatch,
      historyTasks,
      batchResults,
      batchCollections,
      selectedBatchCollectionId,
      polyInfoResults,
      polyInfoComparison,
      polyInfoComparisonLoading,
      archiveLoading,
      selectedPolymerId,
      selectedSampleId,
      entitySearch,
      setEntitySearch,
      entityFilter,
      setEntityFilter,
      selectedEvidence,
      setSelectedEvidence,
      selectedEntity,
      setSelectedEntity,
      setPolyInfoComparison,
      pdfUrl,
      downloadJson,
      checkHealth,
      loadTaskResult,
      refreshHistory,
      refreshBatchResults,
      refreshBatchCollections,
      refreshPolyInfoResults,
      openPolyInfoComparison,
      startExtraction,
      loadSample,
      openResults,
      selectBatchCollection,
      ensureBatchPage,
      openHistoryTask,
      openBatchResult,
      returnToResultList,
      openPolymerPage,
      openSamplePage,
    }),
    [
      mounted, collapsed, contextHolder, selectedFile, dmxApiKey, mineruApiKey, job, health,
      apiChecked, uploading, candidate, graphPayload, dataSource, selectedBatch, historyTasks,
      batchResults, batchCollections, selectedBatchCollectionId, polyInfoResults,
      polyInfoComparison, polyInfoComparisonLoading, archiveLoading, selectedPolymerId,
      selectedSampleId, entitySearch, entityFilter, selectedEvidence, selectedEntity,
      checkHealth, loadTaskResult, refreshHistory, refreshBatchResults, refreshBatchCollections,
      refreshPolyInfoResults, openPolyInfoComparison, startExtraction, loadSample, openResults,
      selectBatchCollection, ensureBatchPage, openHistoryTask, openBatchResult,
      returnToResultList, openPolymerPage, openSamplePage, pdfUrl, downloadJson,
      setSelectedEntity, setSelectedEvidence,
    ],
  );

  return <ExtractionContext.Provider value={value}>{children}</ExtractionContext.Provider>;
}
