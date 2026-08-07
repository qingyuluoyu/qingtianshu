import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StockResearchPage } from "./StockResearchPage";
import { stockResearchQueryKeys } from "./queries";
import { parsedHistory, parsedPeers, parsedStockPage, parsedTasks, workspaceFixture } from "./testFixtures";

function hydratedClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(stockResearchQueryKeys.page("000063", "1y"), parsedStockPage());
  client.setQueryData(stockResearchQueryKeys.history("000063", "1y"), parsedHistory());
  client.setQueryData(stockResearchQueryKeys.peers("000063"), parsedPeers());
  client.setQueryData(stockResearchQueryKeys.theses("000063"), null);
  client.setQueryData(stockResearchQueryKeys.observationTasks("000063"), parsedTasks());
  client.setQueryData(stockResearchQueryKeys.position("000063"), null);
  client.setQueryData(stockResearchQueryKeys.deepStock("000063"), null);
  return client;
}

function renderPage(client: QueryClient, entry = "/stocks/000063", authenticated = true) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route element={<StockResearchPage authenticated={authenticated} />} path="/stocks/:symbol" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("StockResearchPage", () => {
  it("renders header quote, research status empty state and module status panel", () => {
    renderPage(hydratedClient());
    expect(screen.getByRole("heading", { name: /中兴通讯/ })).toBeInTheDocument();
    expect(screen.getByText(/000063\.SZ/)).toBeInTheDocument();
    // 涨跌百分数直通（1.0765 → +1.08%），不缩放。
    expect(screen.getAllByText("+1.08%").length).toBeGreaterThan(0);
    expect(screen.getByText(/日线截至：2026-08-05/)).toBeInTheDocument();
    // thesis empty → 尚未保存当前判断；不是 0、不是接口失败。
    expect(screen.getAllByText(/尚未保存当前判断/).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "创建当前判断" })[0]).toHaveAttribute("href", expect.stringContaining("/advisor"));
    expect(screen.getByText("尚未开启")).toBeInTheDocument();
    // 不伪造 0/7 进度。
    expect(screen.queryByText(/进度 0\/7/)).not.toBeInTheDocument();
    // 模块状态翻译（§6.3）。
    expect(screen.getByText("模块数据状态")).toBeInTheDocument();
    expect(screen.getByText("行情历史")).toBeInTheDocument();
    expect(screen.getAllByText("数据完整").length).toBeGreaterThanOrEqual(9);
    expect(screen.getByText("可用 9/9")).toBeInTheDocument();
    // 关键变化与下一步。
    expect(screen.getByText(/核心研究判断暂未出现实质变化/)).toBeInTheDocument();
    expect(screen.getByText(/收盘与 MA20 36.3445 的相对位置是否变化/)).toBeInTheDocument();
  });

  it("translates a failed module without clearing the rest of the page", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(stockResearchQueryKeys.page("000063", "1y"), parsedStockPage({
      modules: { shareholders: { status: "unavailable", reason: "上游数据源失败", data: null } },
      summary: { available: 8, failed: 1, total: 9, required_failed: [] },
    }));
    renderPage(client);
    expect(screen.getByText(/部分模块暂不可用（失败 1\/9）/)).toBeInTheDocument();
    expect(screen.getByText("股东结构")).toBeInTheDocument();
    expect(screen.getAllByText("当前不可用").length).toBeGreaterThan(0);
    expect(screen.getAllByText("数据完整").length).toBeGreaterThanOrEqual(8);
  });

  it("keeps the research workspace when quote data is unavailable", () => {
    const workspace = workspaceFixture();
    workspace.quote = { ...workspace.quote, price: null, pct_change: null };
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(stockResearchQueryKeys.page("000063", "1y"), parsedStockPage({
      modules: {
        history: { status: "unavailable", reason: "行情供应商超时", data: null },
        workspace: { status: "available", data: workspace },
      },
      summary: { available: 8, failed: 1, total: 9, required_failed: ["history"] },
    }));
    renderPage(client);

    expect(screen.getByText("行情暂不可用")).toBeInTheDocument();
    const workspaceRegion = screen.getByRole("region", { name: "个股研究工作区" });
    expect(within(workspaceRegion).getByText("研究状态")).toBeInTheDocument();
    expect(within(workspaceRegion).getByText("关键变化")).toBeInTheDocument();
  });

  it("renders technical tab with candles, frequency and passthrough indicators", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    renderPage(hydratedClient(), "/stocks/000063?tab=technical&range=1y");
    expect(screen.getByRole("img", { name: "日 K 蜡烛与成交量图" })).toBeInTheDocument();
    expect(screen.getAllByText(/日线截至：2026-08-05/).length).toBeGreaterThan(0);
    expect(screen.getByText(/频率：日线/)).toBeInTheDocument();
    expect(screen.getByText(/adjusted_close 复权收盘参考列/)).toBeInTheDocument();
    expect(screen.getByText("33.85")).toBeInTheDocument();
    expect(screen.getByText("-17.84%")).toBeInTheDocument();
    expect(screen.getByText(/不生成买卖信号/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "近6月" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "近1年" })).toHaveAttribute("aria-pressed", "true");
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("lazy-renders financials tab with periods, drivers and peer comparison", () => {
    renderPage(hydratedClient(), "/stocks/000063?tab=financials");
    expect(screen.getByText("2026一季报")).toBeInTheDocument();
    // 元→亿元为展示层标注：34988057000 元 → 349.88 亿元。
    expect(screen.getByText("349.88 亿元")).toBeInTheDocument();
    expect(screen.getByText("-46.58%")).toBeInTheDocument();
    expect(screen.getByText(/年初累计口径/)).toBeInTheDocument();
    expect(screen.getByText("盈利质量承压")).toBeInTheDocument();
    expect(screen.getByText(/归母净利润较上一年度同类报告期变化 -11.427 亿元/)).toBeInTheDocument();
    expect(screen.getByText(/财务费用变动主要因汇率波动/)).toBeInTheDocument();
    // 同行对比：本股行 + 同行行 + 样本警示。
    expect(screen.getByText(/中兴通讯（本股）/)).toBeInTheDocument();
    expect(screen.getByText("烽火通信")).toBeInTheDocument();
    expect(screen.getByText("122.49")).toBeInTheDocument();
    expect(screen.getByText(/不是完整行业指数/)).toBeInTheDocument();
  });

  it("renders events tab with layered evidence and factual boundaries", () => {
    renderPage(hydratedClient(), "/stocks/000063?tab=events");
    expect(screen.getByText("官方披露")).toBeInTheDocument();
    expect(screen.getByText("可能的支持线索（媒体报道）")).toBeInTheDocument();
    expect(screen.getByText(/中兴通讯中标中国铁塔采购项目/)).toBeInTheDocument();
    expect(screen.getByText(/媒体报道只是定位线索/)).toBeInTheDocument();
    expect(screen.getByText(/不估算事件概率/)).toBeInTheDocument();
    expect(screen.getByText("637,909")).toBeInTheDocument();
    expect(screen.getByText("近六个月统计覆盖 9 家机构：买入 7，增持 2。")).toBeInTheDocument();
    expect(screen.getByText("1.174")).toBeInTheDocument();
    expect(screen.getByText(/不构成买卖建议/)).toBeInTheDocument();
    expect(screen.getByText(/目标价字段不进入证据包/)).toBeInTheDocument();
  });

  it("renders research tab with truthful empty states for 404-backed resources", () => {
    renderPage(hydratedClient(), "/stocks/000063?tab=research");
    expect(screen.getByText(/尚未保存当前判断/)).toBeInTheDocument();
    expect(screen.getByText(/暂无观察任务/)).toBeInTheDocument();
    expect(screen.getByText("暂无该股票的持仓记录")).toBeInTheDocument();
    expect(screen.getByText("深度研究会话尚未建立。")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "开启深度研究" })).toHaveAttribute("href", expect.stringContaining("intent=deep-research"));
    expect(screen.getByText("研究档案")).toBeInTheDocument();
  });

  it("shows login guidance when unauthenticated without firing personal queries", () => {
    renderPage(hydratedClient(), "/stocks/000063?tab=research", false);
    expect(screen.getByText(/登录后可查看你的判断、观察任务、持仓与深度研究/)).toBeInTheDocument();
    expect(screen.getByText(/登录后可查看完整个股研究内容/)).toBeInTheDocument();
    expect(screen.queryByText("研究档案")).not.toBeInTheDocument();
  });

  it("shows per-module skeletons while requests are pending", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPage(client, "/stocks/000063?tab=technical");
    expect(screen.getByText(/正在读取个股研究数据/)).toBeInTheDocument();
    expect(screen.getAllByText("正在读取…").length).toBeGreaterThan(0);
  });
});
