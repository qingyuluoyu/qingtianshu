import { NavLink, Outlet, useLocation } from "react-router-dom";
import type { RefObject } from "react";
import type { AuthSession } from "../api/session";
import { GlobalSearch } from "../features/search/GlobalSearch";
import styles from "./AppShell.module.css";

const navigation = [
  ["/today", "今日总览"],
  ["/screening", "选股策略"],
  ["/watchlist", "我的关注"],
  ["/stocks/000063.SZ", "个股研究"],
  ["/market-data", "行情数据"],
  ["/advisor", "金融顾问"],
  ["/research-center", "研究中心"],
] as const;

type Props = {
  session: AuthSession | null;
  onOpenAuth: () => void;
  onSignOut: () => void;
  authTriggerRef: RefObject<HTMLButtonElement | null>;
};

export function AppShell({ session, onOpenAuth, onSignOut, authTriggerRef }: Props) {
  const location = useLocation();
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar} aria-label="主导航">
        <div className={styles.brand}>清数智算</div>
        <nav>
          {navigation.map(([to, label]) => (
            <NavLink
              className={({ isActive }) => `${styles.navItem} ${isActive ? styles.active : ""}`}
              key={to}
              to={to}
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className={styles.main}>
        <header className={styles.header}>
          <span className={styles.route}>{location.pathname}</span>
          <GlobalSearch />
          {session ? (
            <div className={styles.account}>
              <span>{session.name}</span>
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
