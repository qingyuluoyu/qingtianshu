import { useCallback, useEffect, useRef, useState } from "react";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { getSession, isFormalAccount, signOut } from "../api/session";
import { AppShell } from "../components/AppShell";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { AuthModal } from "../features/auth/AuthModal";
import { useUnauthorizedBoundary } from "../features/auth/useUnauthorizedBoundary";
import { TodayPage } from "../features/today/TodayPage";
import { usePublicEvents } from "../features/today/events";
import { StockResearchPage } from "../features/stock-research/StockResearchPage";
import { WatchlistPage } from "../features/watchlist/WatchlistPage";
import { ScreeningPage } from "../features/screening/ScreeningPage";
import { ResearchCenterPage } from "../features/research-center/ResearchCenterPage";
import { AdvisorPage } from "../features/advisor/AdvisorPage";
import { MarketDataPage } from "../features/market-data/MarketDataPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { SearchPage } from "../features/search/SearchPage";
import { FundsPage } from "../features/funds/FundsPage";
import { RiskProfilePage } from "../features/risk-profile/RiskProfilePage";
import { KnowledgePage } from "../features/knowledge/KnowledgePage";
import { ArticlesPage } from "../features/articles/ArticlesPage";
import { StrategiesPage } from "../features/strategies/StrategiesPage";
import "../styles/global.css";

function isProtectedPath(pathname: string): boolean {
  return ["/today", "/screening", "/watchlist", "/market-data", "/research-center", "/risk-profile", "/knowledge", "/articles", "/strategies"].includes(pathname)
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
    if (session.isError) {
      // 会话查询出错时（端点 404 / 网络异常），清除错误状态并触发登录。
      queryClient.setQueryData(["session"], null);
    }
    if (promptedLocationRef.current === location.key) return;
    promptedLocationRef.current = location.key;
    setAuthOpen(true);
  }, [formal, location.key, location.pathname, session.isLoading, session.isError, queryClient]);

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
        <Route element={<WatchlistPage authenticated={formal} />} path="/watchlist" />
        <Route element={<ScreeningPage authenticated={formal} />} path="/screening" />
        <Route element={<ResearchCenterPage authenticated={formal} />} path="/research-center" />
        <Route element={<AdvisorPage authenticated={formal} />} path="/advisor/:conversationId?" />
        <Route element={<MarketDataPage authenticated={formal} />} path="/market-data" />
        <Route element={<SearchPage authenticated={formal} />} path="/search" />
        <Route element={<FundsPage authenticated={formal} />} path="/funds" />
        <Route element={<RiskProfilePage authenticated={formal} />} path="/risk-profile" />
        <Route element={<KnowledgePage authenticated={formal} />} path="/knowledge" />
        <Route element={<ArticlesPage authenticated={formal} />} path="/articles" />
        <Route element={<StrategiesPage authenticated={formal} />} path="/strategies" />
        <Route element={<NotFoundPage />} path="*" />
      </Route>
    </Routes>
    {authOpen && !formal ? <AuthModal onClose={() => setAuthOpen(false)} returnFocusRef={authTriggerRef} /> : null}
  </>;
}

export function App() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } }));
  return <QueryClientProvider client={client}><BrowserRouter><ErrorBoundary><ProductApp /></ErrorBoundary></BrowserRouter></QueryClientProvider>;
}
