
import { AlertTriangle, ArrowLeft, CheckCircle2, Download, FileSearch, FileUp, FlaskConical, GitBranchPlus, GitCompareArrows, History as HistoryIcon, Layers3, PanelLeftClose } from "lucide-react";
import { Button, ConfigProvider, Space, Tag, message } from "antd";
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

  const navItems = [
    { key: "upload", label: "上传文献", icon: FileUp, href: "/upload" },
    { key: "history", label: "历史任务", icon: HistoryIcon, href: "/history" },
    { key: "batch", label: "批处理结果", icon: Layers3, href: "/batch" },
    { key: "polyinfo", label: "批次对照", icon: GitCompareArrows, href: "/polyinfo" },
    { key: "sample", label: "样品详情", icon: FlaskConical, href: "/sample" },
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
        <aside className="tool-sidebar">
          <div className="tool-brand">
            {collapsed ? (
              <button className="brand-symbol as-toggle" aria-label="展开侧栏" title="展开侧栏" onClick={() => setCollapsed(false)}>
                <img src={logoUrl} alt="PolymerLit logo" width={30} height={30} />
              </button>
            ) : (
              <div className="brand-symbol"><img src={logoUrl} alt="PolymerLit logo" width={30} height={30} /></div>
            )}
            {!collapsed && (
              <div className="brand-title">
                <strong className="brand-name">PolymerLit <em>Extractor</em></strong>
                <span className="brand-sub">高分子文献智能抽取</span>
              </div>
            )}
            {!collapsed && (
              <button className="brand-collapse" aria-label="收起侧栏" onClick={() => setCollapsed(true)}>
                <PanelLeftClose size={18} />
              </button>
            )}
          </div>
          <nav className="side-nav" aria-label="主导航">
            {!collapsed && <p className="side-group-title">文献抽取</p>}
            {navItems.slice(0, 2).map((item) => {
              const Icon = item.icon;
              const active = isActive(item.key);
              return (
                <Link key={item.key} to={item.href} className={active ? "active" : ""} title={item.label}>
                  <span className={`side-nav-icon side-nav-icon-${item.key}`} aria-hidden="true"><Icon size={17} strokeWidth={2} /></span>
                  {!collapsed && <span>{item.label}</span>}
                </Link>
              );
            })}
            {!collapsed && <p className="side-group-title">结果浏览</p>}
            {navItems.slice(2).map((item) => {
              const Icon = item.icon;
              const active = isActive(item.key);
              return (
                <Link key={item.key} to={item.href} className={active ? "active" : ""} title={item.label}>
                  <span className={`side-nav-icon side-nav-icon-${item.key}`} aria-hidden="true"><Icon size={17} strokeWidth={2} /></span>
                  {!collapsed && <span>{item.label}</span>}
                  {!collapsed && item.key === "sample" && !candidate && <i>待生成</i>}
                </Link>
              );
            })}
          </nav>
          <div className="side-secondary">
            <Button type="text" href={`${API_BASE}/api/reports/evolution`} target="_blank" title="最新进化版本与实验结果" icon={<GitBranchPlus size={17} strokeWidth={2} />}>{!collapsed && "最新进化结果"}</Button>
            {/* <button title="系统设置"><Settings size={16} strokeWidth={1.8} />{!collapsed && <span>系统设置</span>}</button> */}
            {!collapsed && <Link to="/upload" className="side-login-btn" title="系统设置" onClick={(e) => { e.preventDefault(); message.info("系统设置功能正在开发中，敬请期待"); }}>系统设置</Link>}
          </div>
        </aside>

        <main className="tool-content">
          {onDetailPage && (
            <div className={segment === "sample" ? "detail-topbar sample-no-back" : "detail-topbar"}>
              {segment !== "sample" && (
                <Button icon={<ArrowLeft size={15} />} onClick={handleBannerBack}>{backLabel}</Button>
              )}
              <Space>
                <Button href={pdfUrl} target="_blank" icon={<FileSearch size={15} />}>原文</Button>
                <Button className="start-btn" type="primary" onClick={downloadJson} icon={<Download size={15} />}>导出数据</Button>
              </Space>
            </div>
          )}
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
          <Outlet />
        </main>

        <nav className="mobile-nav" aria-label="移动端导航">
          {navItems.map((item) => { const Icon = item.icon; return <Link key={item.key} to={item.href} className={isActive(item.key) ? "active" : ""}><span className={`side-nav-icon side-nav-icon-${item.key}`} aria-hidden="true"><Icon size={18} strokeWidth={2} /></span><span>{item.label}</span></Link>; })}
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
