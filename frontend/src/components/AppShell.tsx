import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect, useState, type RefObject } from "react";
import type { AuthSession } from "../api/session";
import { GlobalSearch } from "../features/search/GlobalSearch";
import styles from "./AppShell.module.css";

type IconName = "today" | "watch" | "stock" | "ai" | "review" | "market" | "screen" | "strategy" | "knowledge" | "risk";

const primaryNavigation = [
  { to: "/today", label: "今日观察", icon: "today" },
  { to: "/watchlist", label: "我的关注", icon: "watch" },
  { to: "/stocks/000063.SZ", label: "个股研究", icon: "stock" },
  { to: "/advisor", label: "AI 研究", icon: "ai" },
  { to: "/research-center", label: "复盘中心", icon: "review" },
] as const;

const auxiliaryNavigation = [
  { to: "/market-data", label: "行情数据", icon: "market" },
  { to: "/screening", label: "透明选股", icon: "screen" },
  { to: "/strategies", label: "策略工具", icon: "strategy" },
  { to: "/knowledge", label: "研究资料", icon: "knowledge" },
  { to: "/risk-profile", label: "风险测评", icon: "risk" },
] as const;

const pageLabels: Record<string, string> = {
  "/today": "今日观察",
  "/market-data": "行情数据",
  "/screening": "透明选股",
  "/watchlist": "我的关注",
  "/research-center": "复盘中心",
  "/advisor": "AI 研究",
  "/search": "搜索",
  "/funds": "基金",
  "/risk-profile": "风险测评",
  "/knowledge": "研究资料",
  "/articles": "文章",
  "/strategies": "策略工具",
};

function pageLabel(pathname: string): string {
  if (/^\/stocks\/[^/]+$/.test(pathname)) return "个股研究";
  if (/^\/advisor(?:\/[^/]+)?$/.test(pathname)) return "AI 研究";
  return pageLabels[pathname] ?? "清数智算";
}

function NavIcon({ name }: { name: IconName }) {
  const path = {
    today: "M4 13a8 8 0 1 1 16 0M12 5v8l4 2",
    watch: "M12 20s-7-4.35-7-10a4 4 0 0 1 7-2.65A4 4 0 0 1 19 10c0 5.65-7 10-7 10Z",
    stock: "M4 19V9m5 10V5m6 14v-7m5 7V3",
    ai: "M6 17 9 7l3 10 3-10 3 10M7.2 13h3.6M15 7v10",
    review: "M5 4h14v16H5zM8 8h8M8 12h5M8 16h7",
    market: "M4 18 9 12l4 3 7-9M16 6h4v4",
    screen: "M4 6h16M7 12h10m-7 6h4M8 4v4m8 2v4m-4 2v4",
    strategy: "M5 19 19 5M7 5h4v4M13 15h4v4",
    knowledge: "M5 4h9a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3V4Zm3 3h6M8 11h6M8 15h4",
    risk: "M12 3 5 6v5c0 4.6 2.8 8 7 10 4.2-2 7-5.4 7-10V6l-7-3Zm0 5v5m0 3h.01",
  }[name];
  return <svg aria-hidden="true" className={styles.navIcon} fill="none" viewBox="0 0 24 24"><path d={path} stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" /></svg>;
}

type Props = {
  session: AuthSession | null;
  onOpenAuth: () => void;
  onSignOut: () => void;
  authTriggerRef: RefObject<HTMLButtonElement | null>;
};

export function AppShell({ session, onOpenAuth, onSignOut, authTriggerRef }: Props) {
  const location = useLocation();
  const [navigationOpen, setNavigationOpen] = useState(false);

  useEffect(() => setNavigationOpen(false), [location.pathname]);

  const navLink = ({ to, label, icon }: (typeof primaryNavigation)[number] | (typeof auxiliaryNavigation)[number]) => (
    <NavLink aria-label={label} className={({ isActive }) => `${styles.navItem} ${isActive ? styles.active : ""}`} key={to} to={to}>
      <NavIcon name={icon} />
      <span>{label}</span>
      <span aria-hidden="true" className={styles.navArrow}>›</span>
    </NavLink>
  );

  return (
    <div className={styles.shell}>
      <aside aria-label="主导航" className={`${styles.sidebar} ${navigationOpen ? styles.sidebarOpen : ""}`} id="primary-navigation">
        <div className={styles.brand}>
          <span aria-hidden="true" className={styles.brandMark}>清</span>
          <span><strong>清数智算</strong><small>智能投研工作台</small></span>
        </div>
        <nav aria-label="产品导航" className={styles.navigation}>
          <section aria-label="核心工作流" className={styles.navGroup}>
            <p className={styles.navGroupLabel}>核心工作流</p>
            {primaryNavigation.map(navLink)}
          </section>
          <section aria-label="辅助工具" className={styles.navGroup}>
            <p className={styles.navGroupLabel}>辅助工具</p>
            {auxiliaryNavigation.map(navLink)}
          </section>
        </nav>
        <div className={styles.sidebarNote}>
          <span>研究边界</span>
          <strong>事实、证据、行动分开记录</strong>
          <small>系统不生成买卖或仓位指令</small>
        </div>
      </aside>
      {navigationOpen ? <button aria-label="关闭主导航" className={styles.backdrop} onClick={() => setNavigationOpen(false)} type="button" /> : null}
      <div className={styles.main}>
        <header className={styles.header}>
          <button aria-controls="primary-navigation" aria-expanded={navigationOpen} aria-label={navigationOpen ? "关闭主导航" : "打开主导航"} className={styles.menuButton} onClick={() => setNavigationOpen((open) => !open)} type="button">
            <span aria-hidden="true">☰</span>
          </button>
          <div className={styles.routeBlock}>
            <span className={styles.routeEyebrow}>研究工作台</span>
            <span className={styles.route} data-testid="current-page-label">{pageLabel(location.pathname)}</span>
          </div>
          <GlobalSearch />
          {session ? (
            <div className={styles.account}>
              <span aria-hidden="true" className={styles.avatar}>{session.name.trim().slice(0, 1).toUpperCase()}</span>
              <span className={styles.accountName}>{session.name}</span>
              <button onClick={onSignOut} type="button">退出</button>
            </div>
          ) : (
            <button className={styles.loginButton} onClick={onOpenAuth} ref={authTriggerRef} type="button">登录 / 注册</button>
          )}
        </header>
        <main className={styles.content}><Outlet /></main>
      </div>
      <nav aria-label="移动产品导航" className={styles.mobileNav}>
        {primaryNavigation.map(({ to, label, icon }) => (
          <NavLink className={({ isActive }) => `${styles.mobileNavItem} ${isActive ? styles.mobileActive : ""}`} key={to} to={to}>
            <NavIcon name={icon} />
            <span>{label.replace("今日观察", "今日").replace("我的关注", "关注").replace("个股研究", "个股").replace("AI 研究", "AI").replace("复盘中心", "复盘")}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
