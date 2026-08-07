import { useEffect, useRef, useState, type RefObject } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import type { AuthSession } from "../api/session";
import { GlobalSearch } from "../features/search/GlobalSearch";
import styles from "./AppShell.module.css";

type NavigationItem = { to: string; label: string; matchPrefix?: string };

const navigation: readonly NavigationItem[] = [
  { to: "/today", label: "今日观察" },
  { to: "/screening", label: "透明选股" },
  { to: "/watchlist", label: "我的关注" },
  { to: "/stocks/000063.SZ", label: "个股研究", matchPrefix: "/stocks/" },
  { to: "/advisor", label: "金融顾问", matchPrefix: "/advisor" },
  { to: "/research-center", label: "研究中心" },
];

const routeTitles: Record<string, string> = {
  "/today": "今日观察",
  "/screening": "透明选股",
  "/watchlist": "我的关注",
  "/advisor": "金融顾问",
  "/research-center": "研究中心",
  "/market-data": "行情数据",
};

function routeTitle(pathname: string): string {
  if (pathname.startsWith("/stocks/")) return "个股研究";
  if (pathname.startsWith("/advisor/")) return "金融顾问";
  return routeTitles[pathname] ?? "清数智算";
}

type Props = {
  session: AuthSession | null;
  onOpenAuth: () => void;
  onSignOut: () => void;
  authTriggerRef: RefObject<HTMLButtonElement | null>;
};

export function AppShell({ session, onOpenAuth, onSignOut, authTriggerRef }: Props) {
  const location = useLocation();
  const menuTriggerRef = useRef<HTMLButtonElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  const closeMenu = (restoreFocus = false) => {
    setMenuOpen(false);
    if (restoreFocus) menuTriggerRef.current?.focus();
  };

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!menuOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeMenu(true);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  const accountLabel = session?.account ?? session?.name ?? session?.masked_phone ?? "已登录用户";

  return (
    <div className={styles.shell}>
      <aside className={`${styles.sidebar} ${menuOpen ? styles.sidebarOpen : ""}`} id="formal-navigation">
        <div className={styles.brand}>清数智算</div>
        <nav aria-label="主导航">
          {navigation.map(({ to, label, matchPrefix }) => {
            const active = matchPrefix ? location.pathname.startsWith(matchPrefix) : location.pathname === to;
            return (
              <NavLink
                aria-current={active ? "page" : undefined}
                className={`${styles.navItem} ${active ? styles.active : ""}`}
                key={to}
                onClick={() => setMenuOpen(false)}
                to={to}
              >
                {label}
              </NavLink>
            );
          })}
        </nav>
      </aside>
      {menuOpen ? <button aria-label="关闭主导航遮罩" className={styles.navBackdrop} onClick={() => closeMenu(true)} type="button" /> : null}
      <div className={styles.main}>
        <header className={styles.header}>
          <div className={styles.routeArea}>
            <button
              aria-controls="formal-navigation"
              aria-expanded={menuOpen}
              aria-label={menuOpen ? "关闭主导航" : "打开主导航"}
              className={styles.menuButton}
              onClick={() => setMenuOpen((current) => !current)}
              ref={menuTriggerRef}
              type="button"
            >
              <span aria-hidden="true">☰</span>
            </button>
            <span className={styles.route} data-testid="route-title">{routeTitle(location.pathname)}</span>
          </div>
          <GlobalSearch />
          {session ? (
            <div className={styles.account}>
              <span>{accountLabel}</span>
              <button onClick={onSignOut} type="button">退出</button>
            </div>
          ) : (
            <button onClick={onOpenAuth} ref={authTriggerRef} type="button">登录 / 注册</button>
          )}
        </header>
        <main className={styles.content}><Outlet /></main>
      </div>
    </div>
  );
}
