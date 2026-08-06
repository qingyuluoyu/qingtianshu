import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useState } from "react";
import type { RefObject } from "react";
import type { AuthSession } from "../api/session";
import { GlobalSearch } from "../features/search/GlobalSearch";
import styles from "./AppShell.module.css";

const navigation = [
  ["/today", "今日观察"],
  ["/screening", "透明选股"],
  ["/watchlist", "我的关注"],
  ["/stocks/000063.SZ", "个股研究"],
  ["/advisor", "金融顾问"],
  ["/research-center", "研究中心"],
] as const;

function routeTitle(pathname: string): string {
  if (pathname === "/today") return "今日观察";
  if (pathname === "/screening") return "透明选股";
  if (pathname === "/watchlist") return "我的关注";
  if (/^\/stocks\/[^/]+$/.test(pathname)) return "个股研究";
  if (/^\/advisor(?:\/[^/]+)?$/.test(pathname)) return "金融顾问";
  if (pathname === "/research-center") return "研究中心";
  if (pathname === "/market-data") return "行情数据（兼容入口）";
  return "清数智算";
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
  return (
    <div className={styles.shell}>
      {navigationOpen ? <button aria-label="关闭导航遮罩" className={styles.navBackdrop} onClick={() => setNavigationOpen(false)} type="button" /> : null}
      <aside className={`${styles.sidebar} ${navigationOpen ? styles.sidebarOpen : ""}`} aria-label="主导航" id="primary-navigation">
        <div className={styles.brand}>清数智算</div>
        <nav aria-label="产品页面">
          {navigation.map(([to, label]) => (
            <NavLink
              className={({ isActive }) => `${styles.navItem} ${isActive ? styles.active : ""}`}
              key={to}
              onClick={() => setNavigationOpen(false)}
              to={to}
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className={styles.main}>
        <header className={styles.header}>
          <button
            aria-controls="primary-navigation"
            aria-expanded={navigationOpen}
            aria-label={navigationOpen ? "关闭主导航" : "打开主导航"}
            className={styles.mobileNavButton}
            onClick={() => setNavigationOpen((open) => !open)}
            type="button"
          >
            <span aria-hidden="true">☰</span>
          </button>
          <span aria-live="polite" className={styles.route}>{routeTitle(location.pathname)}</span>
          <GlobalSearch />
          <div className={styles.sessionControl}>
            {session ? (
              <div className={styles.account}>
                <span>{session.name}</span>
                <button onClick={onSignOut} type="button">退出</button>
              </div>
            ) : (
              <button onClick={onOpenAuth} ref={authTriggerRef} type="button">登录 / 注册</button>
            )}
          </div>
        </header>
        <main className={styles.content}><Outlet /></main>
      </div>
    </div>
  );
}
