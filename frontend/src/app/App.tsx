import { useCallback, useEffect, useRef, useState } from "react";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { getSession, isFormalAccount, signOut } from "../api/session";
import { AppShell } from "../components/AppShell";
import { AuthModal } from "../features/auth/AuthModal";
import { useUnauthorizedBoundary } from "../features/auth/useUnauthorizedBoundary";
import { TodayPage } from "../features/today/TodayPage";
import { usePublicEvents } from "../features/today/events";
import { StockResearchPage } from "../features/stock-research/StockResearchPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { PlaceholderPage } from "../pages/PlaceholderPage";
import "../styles/global.css";

const pages = [
  ["/screening", "选股策略", "解释筛选条件、结果来源和证据边界。"],
  ["/watchlist", "我的关注", "管理个人关注标的、判断版本与观察事项。"],
  ["/market-data", "行情数据", "集中呈现指数、广度、板块与全球市场行情。"],
  ["/advisor/:conversationId?", "金融顾问", "承载个人金融问答与可追溯研究对话。"],
  ["/research-center", "研究中心", "汇集可核验研究产出、变化和结论。"],
] as const;

function isProtectedPath(pathname: string): boolean {
  return ["/today", "/screening", "/watchlist", "/market-data", "/research-center"].includes(pathname)
    || /^\/stocks\/[^/]+$/.test(pathname)
    || /^\/advisor(?:\/[^/]+)?$/.test(pathname);
}

function ProductApp() {
  const queryClient = useQueryClient();
  const location = useLocation();
  const session = useQuery({ queryKey: ["session"], queryFn: getSession, retry: false });
  const [authOpen, setAuthOpen] = useState(false);
  const promptedLocationRef = useRef<string | null>(null);
  const authTriggerRef = useRef<HTMLButtonElement>(null);
  const formal = isFormalAccount(session.data ?? null);
  const eventState = usePublicEvents(formal);

  useEffect(() => {
    if (session.isLoading || formal || !isProtectedPath(location.pathname)) return;
    if (promptedLocationRef.current === location.key) return;
    promptedLocationRef.current = location.key;
    setAuthOpen(true);
  }, [formal, location.key, location.pathname, session.isLoading]);

  useEffect(() => {
    if (formal) setAuthOpen(false);
  }, [formal]);

  const handleUnauthorized = useCallback(() => {
    promptedLocationRef.current = location.key;
    queryClient.clear();
    queryClient.setQueryData(["session"], null);
    setAuthOpen(true);
  }, [location.key, queryClient]);
  useUnauthorizedBoundary(formal, handleUnauthorized);

  const logout = async () => {
    await signOut();
    promptedLocationRef.current = location.key;
    queryClient.clear();
    queryClient.setQueryData(["session"], null);
    setAuthOpen(true);
  };
  return <>
    <Routes>
      <Route element={<AppShell authTriggerRef={authTriggerRef} onOpenAuth={() => setAuthOpen(true)} onSignOut={() => void logout()} session={formal ? session.data ?? null : null} />}>
        <Route index element={<Navigate replace to="/today" />} />
        <Route element={<TodayPage authenticated={formal} eventState={eventState} />} path="/today" />
        <Route element={<StockResearchPage authenticated={formal} />} path="/stocks/:symbol" />
        {pages.map(([path, title, responsibility]) => <Route element={<PlaceholderPage key={path} locked={!formal} responsibility={responsibility} title={title} />} key={path} path={path} />)}
        <Route element={<NotFoundPage />} path="*" />
      </Route>
    </Routes>
    {authOpen && !formal ? <AuthModal onClose={() => setAuthOpen(false)} returnFocusRef={authTriggerRef} /> : null}
  </>;
}

export function App() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } }));
  return <QueryClientProvider client={client}><BrowserRouter><ProductApp /></BrowserRouter></QueryClientProvider>;
}
