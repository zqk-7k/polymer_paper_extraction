
import { AlertTriangle, ArrowLeft, CheckCircle2, Download, FileSearch } from "lucide-react";
import { Button, ConfigProvider, Space, Tag, Tooltip, message } from "antd";
import zhCN from "antd/locale/zh_CN";
import { Link, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { ExtractionProvider, useExtraction } from "./store/extraction";
import { displayPaperTitle } from "./utils/format";
import { API_BASE } from "./types";
import { EntityDrawer, EvidenceDrawer, PolyInfoComparisonDrawer } from "./components/drawers";

import logoUrl from "./assets/logo2.png";

function AppShell() {
  const pathname = useLocation().pathname;
  const navigate = useNavigate();
  const segment = pathname.split("/")[1] || "upload";
  const store = useExtraction();
  const {
    mounted, collapsed, setCollapsed, contextHolder, candidate, dataSource,
    selectedEvidence, setSelectedEvidence, selectedEntity, setSelectedEntity,
    polyInfoComparison, polyInfoComparisonLoading, setPolyInfoComparison,
    pdfUrl, downloadJson, returnToResultList, selectedPolymerId,
  } = store;
  const onDetailPage = Boolean(candidate) && ["results", "polymer", "sample"].includes(segment);
  const showCandidateWarning = Boolean(candidate) && candidate.publication.validation_status === "not_validated";
  const backLabel =
    segment === "polymer" ? "返回抽取结果"
    : dataSource === "batch" ? "返回批处理列表"
    : dataSource === "sample" ? "返回上传页"
    : dataSource === "task" ? "返回历史任务"
    : "返回结果列表";
  const handleBannerBack = () => {
    if (segment === "results") returnToResultList();
    else if (segment === "polymer") navigate("/results");
    else navigate(selectedPolymerId ? "/polymer" : "/results");
  };
  const candidateTooltip = showCandidateWarning
    ? `候选结果 · 尚未完成科学语义校验。结论仅供人工审核，不可直接入库或统计，请以原文证据与 PDF 为准。${dataSource === "task" ? "（网页抽取）" : dataSource === "batch" ? "（离线批处理）" : dataSource === "sample" ? "（内置示例）" : ""}`
    : candidate ? displayPaperTitle(candidate.paper, "抽取结果") : "抽取结果";

  const navItems = [
    { key: "upload", label: "上传文献", path: "M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12", href: "/upload" },
    { key: "history", label: "历史任务", path: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z", href: "/history" },
    { key: "batch", label: "批处理结果", path: "M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10", href: "/batch" },
    { key: "polyinfo", label: "批次对照", path: "M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4", href: "/polyinfo" },
    { key: "sample", label: "样品详情", path: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z", href: "/sample" },
  ];
  const isActive = (key: string) => segment === key;

  if (!mounted) {
    return (
      <main className="portal-boot" aria-label="正在加载 PolymerLit Extractor">
        <div className="boot-logo"><img src={logoUrl} alt="PolymerLit" width={52} height={52} /></div>
        <strong>PolymerLit Extractor</strong>
        <span>正在加载文献抽取工作台…</span>
      </main>
    );
  }

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#1f5eff",
          colorInfo: "#1f5eff",
          colorSuccess: "#16a34a",
          colorWarning: "#d97706",
          colorError: "#e5484d",
          colorText: "#171717",
          colorTextSecondary: "#6b7280",
          colorBorder: "#e8eaee",
          colorBgLayout: "#f4f5f7",
          colorBgContainer: "#FFFFFF",
          controlHeight: 34,
          borderRadius: 10,
          fontSize: 13,
          fontFamily: 'MiSans, "PingFang SC", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
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
      <div className={`tool-shell precision-ui no-topbar ${collapsed ? "is-collapsed" : ""}`}>
        <aside className="tool-sidebar" data-purpose="sidebar-navigation">
          <div className="tool-brand">
            <div className="brand-id">
              {collapsed ? (
                <button type="button" className="brand-mark as-toggle" aria-label="展开侧边栏" title="展开侧边栏" onClick={() => setCollapsed(false)}>
                  <svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
                    <path d="M7.5 6.5v19" stroke="#fff" strokeWidth="3.4" strokeLinecap="round" />
                    <path d="M7.5 6.5h6.8a4.9 4.9 0 0 1 0 9.8H7.5" stroke="#fff" strokeWidth="3.4" strokeLinecap="round" strokeLinejoin="round" />
                    <path d="M19.5 8.2h6M19.5 16h5M19.5 23.8h6" stroke="#c7d2fe" strokeWidth="3.4" strokeLinecap="round" />
                    <path d="M19.5 8.2v15.6" stroke="#fff" strokeWidth="3.4" strokeLinecap="round" />
                    <circle cx="19.5" cy="8.2" r="2.1" fill="#fff" />
                    <circle cx="7.5" cy="25.5" r="2.1" fill="#c7d2fe" />
                  </svg>
                </button>
              ) : (
                <span className="brand-mark" aria-hidden="true">
                  <svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
                    <path d="M7.5 6.5v19" stroke="#fff" strokeWidth="3.4" strokeLinecap="round" />
                    <path d="M7.5 6.5h6.8a4.9 4.9 0 0 1 0 9.8H7.5" stroke="#fff" strokeWidth="3.4" strokeLinecap="round" strokeLinejoin="round" />
                    <path d="M19.5 8.2h6M19.5 16h5M19.5 23.8h6" stroke="#c7d2fe" strokeWidth="3.4" strokeLinecap="round" />
                    <path d="M19.5 8.2v15.6" stroke="#fff" strokeWidth="3.4" strokeLinecap="round" />
                    <circle cx="19.5" cy="8.2" r="2.1" fill="#fff" />
                    <circle cx="7.5" cy="25.5" r="2.1" fill="#c7d2fe" />
                  </svg>
                </span>
              )}
              {!collapsed && (
                <span className="brand-text">
                  <strong className="brand-name">PolymerLit <em>Extractor</em></strong>
                  <span className="brand-sub">高分子文献智能抽取</span>
                </span>
              )}
            </div>
            {!collapsed && (
              <button className="brand-collapse" aria-label="收起侧边栏" title="收起侧边栏" onClick={() => setCollapsed(true)}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d="M11 19l-7-7 7-7m8 14l-7-7 7-7" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </button>
            )}
          </div>
          <nav className="side-nav custom-scroll" aria-label="主导航">
            <div className="side-group">
              {!collapsed && <p className="side-group-title">文献抽取</p>}
              <div className="side-links">
                {navItems.slice(0, 2).map((item) => {
                  const active = isActive(item.key);
                  return (
                    <Link key={item.key} to={item.href} className={active ? "active" : ""} title={item.label}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d={item.path} strokeLinecap="round" strokeLinejoin="round" /></svg>
                      {!collapsed && <span>{item.label}</span>}
                    </Link>
                  );
                })}
              </div>
            </div>
            <div className="side-group">
              {!collapsed && <p className="side-group-title">结果浏览</p>}
              <div className="side-links">
                {navItems.slice(2).map((item) => {
                  const active = isActive(item.key);
                  return (
                    <Link key={item.key} to={item.href} className={active ? "active" : ""} title={item.label}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d={item.path} strokeLinecap="round" strokeLinejoin="round" /></svg>
                      {!collapsed && <span>{item.label}</span>}
                    </Link>
                  );
                })}
              </div>
            </div>
          </nav>
          <div className="side-secondary">
            <a className="side-evo" href={`${API_BASE}/api/reports/evolution`} target="_blank" rel="noreferrer" title="最新进化版本与实验结果">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d="M13 10V3L4 14h7v7l9-11h-7z" strokeLinecap="round" strokeLinejoin="round" /></svg>
              {!collapsed && <span>最新进化结果</span>}
            </a>
            {!collapsed ? (
              <Link to="/upload" className="side-settings-btn" title="系统设置" onClick={(e) => { e.preventDefault(); message.info("系统设置功能正在开发中，敬请期待"); }}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" strokeLinecap="round" strokeLinejoin="round" /><path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" strokeLinecap="round" strokeLinejoin="round" /></svg>
                <span>系统设置</span>
              </Link>
            ) : (
              <button type="button" className="side-settings-btn is-icon" title="系统设置" onClick={() => message.info("系统设置功能正在开发中，敬请期待")}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" strokeLinecap="round" strokeLinejoin="round" /><path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </button>
            )}
          </div>
        </aside>

        <main className="tool-content">
          {onDetailPage && (
            <div className={segment === "sample" ? "detail-topbar sample-no-back" : "detail-topbar"}>
              {segment !== "sample" && (
                <Button icon={<ArrowLeft size={15} />} onClick={handleBannerBack}>{backLabel}</Button>
              )}
              <Space>
                <Tooltip placement="bottom" title={candidateTooltip}><span className="detail-help" style={{ display: "inline-grid", placeItems: "center", width: 22, height: 22, borderRadius: "50%", border: showCandidateWarning ? "1px solid #f4c98f" : "1px solid #c3cbd6", background: showCandidateWarning ? "#fff1df" : "transparent", color: showCandidateWarning ? "#a34f05" : "#7b879b", fontSize: 12, fontWeight: 700, lineHeight: 1, cursor: "help" }}>{showCandidateWarning ? "!" : "?"}</span></Tooltip>
                <Button href={pdfUrl} target="_blank" icon={<FileSearch size={15} />}>原文</Button>
                <Button className="start-btn" type="primary" onClick={downloadJson} icon={<Download size={15} />}>导出数据</Button>
              </Space>
            </div>
          )}
          {/* candidate-banner 已注释隐藏（sample / results / polymer 页面不再展示）。
          {onDetailPage && (
            <div className="candidate-banner in-content" role="note">
              {showCandidateWarning ? (
                <>
                  <span className="candidate-banner-icon"><AlertTriangle size={15} /></span>
                  <div className="candidate-banner-body"><strong>候选结果 · 尚未完成科学语义校验</strong><span>结论仅供人工审核，不可直接入库或统计。请以原文证据与 PDF 为准。</span></div>
                  {dataSource === "task" && <Tag color="blue">网页抽取</Tag>}{dataSource === "batch" && <Tag color="purple">离线批处理</Tag>}{dataSource === "sample" && <Tag>内置示例</Tag>}
                </>
              ) : (
                <>
                  <span className="candidate-banner-icon is-ok"><CheckCircle2 size={15} /></span>
                  <div className="candidate-banner-body"><strong>{candidate ? displayPaperTitle(candidate.paper, "抽取结果") : "抽取结果"}</strong></div>
                </>
              )}
            </div>
          )}
          */}
          <Outlet />
        </main>

        <nav className="mobile-nav" aria-label="移动端导航">
          {navItems.map((item) => { return <Link key={item.key} to={item.href} className={isActive(item.key) ? "active" : ""}><svg viewBox="0 0 24 24" width={18} height={18} fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d={item.path} strokeLinecap="round" strokeLinejoin="round" /></svg><span>{item.label}</span></Link>; })}
        </nav>
      </div>

      <EvidenceDrawer evidence={selectedEvidence} pdfUrl={pdfUrl} onClose={() => setSelectedEvidence(null)} />
      <EntityDrawer entity={selectedEntity} evidence={candidate?.evidence || []} onEvidence={(item) => { setSelectedEntity(null); setSelectedEvidence(item); }} onClose={() => setSelectedEntity(null)} />
      <PolyInfoComparisonDrawer comparison={polyInfoComparison} loading={polyInfoComparisonLoading} onClose={() => setPolyInfoComparison(null)} />
    </ConfigProvider>
  );
}

import Batch from "./pages/Batch";
import History from "./pages/History";
import PolyInfo from "./pages/PolyInfo";
import Polymer from "./pages/Polymer";
import Results from "./pages/Results";
import Sample from "./pages/Sample";
import Upload from "./pages/Upload";

export default function App() {
  return (
    <ExtractionProvider>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/upload" replace />} />
          <Route path="upload" element={<Upload />} />
          <Route path="history" element={<History />} />
          <Route path="batch" element={<Batch />} />
          <Route path="polyinfo" element={<PolyInfo />} />
          <Route path="results" element={<Results />} />
          <Route path="polymer" element={<Polymer />} />
          <Route path="sample" element={<Sample />} />
          <Route path="*" element={<Navigate to="/upload" replace />} />
        </Route>
      </Routes>
    </ExtractionProvider>
  );
}
