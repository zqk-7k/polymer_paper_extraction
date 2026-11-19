import { Link } from "react-router-dom";
import { message } from "antd";
import { API_BASE } from "../types";
import logoUrl from "../assets/logo2.png";
export const portalNavItems = [
    { key: "upload", label: "上传文献", path: "M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12", href: "/upload" },
    { key: "history", label: "历史任务", path: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z", href: "/history" },
    { key: "batch", label: "批处理结果", path: "M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10", href: "/batch" },
    { key: "polyinfo", label: "批次对照", path: "M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4", href: "/polyinfo" },
    { key: "sample", label: "样品详情", path: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z", href: "/sample" },
  ];

export default function PortalSidebar({ collapsed, setCollapsed, segment }: { collapsed: boolean; setCollapsed: (value: boolean) => void; segment: string }) {
  const isActive = (key: string) => segment === key;
return (        <aside className="tool-sidebar" data-purpose="sidebar-navigation">
          <div className="tool-brand">
            <div className="brand-id">
              <button type="button" className="brand-logo-btn as-toggle" onClick={collapsed ? () => setCollapsed(false) : undefined} aria-label={collapsed ? "展开侧边栏" : "PolymerLit"} title={collapsed ? "展开侧边栏" : "PolymerLit"} style={collapsed ? { cursor: "pointer" } : undefined} disabled={!collapsed}><img src={logoUrl} alt="PolymerLit" className="brand-logo-img" /></button>
              
              {!collapsed && (
                <span className="brand-text">
                  <strong className="brand-name">PolymerLit</strong>
                  <span className="brand-sub">高分子文献智能抽取</span>
                </span>
              )}
            </div>
            {!collapsed && (
              <button className="brand-collapse" aria-label="收起侧边栏" title="收起侧边栏" onClick={() => setCollapsed(true)}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16M16 9l-3 3 3 3" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </button>
            )}
          </div>
          <nav className="side-nav custom-scroll" aria-label="主导航">
            <div className="side-group">
              {!collapsed && <p className="side-group-title">文献抽取</p>}
              <div className="side-links">
                {portalNavItems.slice(0, 2).map((item) => {
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
                {portalNavItems.slice(2).map((item) => {
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
        </aside>);
}

