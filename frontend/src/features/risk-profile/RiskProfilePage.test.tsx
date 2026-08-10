import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthSession } from "../../api/session";
import { confirmRiskProfile, getRiskProfile, saveRiskProfileDraft } from "./api";
import { RiskProfilePage } from "./RiskProfilePage";

vi.mock("./api", () => ({
  getRiskProfile: vi.fn(),
  saveRiskProfileDraft: vi.fn(),
  confirmRiskProfile: vi.fn(),
}));

const mockGetRiskProfile = vi.mocked(getRiskProfile);

const session: AuthSession = {
  id: "user-1",
  account: "user@example.com",
  name: "张三",
  masked_phone: "138****0000",
  auth_type: "account",
  is_registered: true,
  created_at: "2026-08-01T00:00:00+08:00",
  session_expires_at: "2026-08-10T12:00:00+08:00",
};

function renderPage(authenticated = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RiskProfilePage authenticated={authenticated} session={authenticated ? session : null} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockGetRiskProfile.mockResolvedValue({
    id: "risk-1",
    status: "confirmed",
    riskLevel: "balanced",
    riskLabel: "稳健型",
    score: 42,
    answers: {},
    confirmedAt: "2026-08-06T08:00:00+08:00",
    draftUpdatedAt: null,
    boundary: "风险档案只反映已确认的个人偏好。",
  });
  vi.mocked(saveRiskProfileDraft).mockResolvedValue(true);
  vi.mocked(confirmRiskProfile).mockResolvedValue(null);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("RiskProfilePage", () => {
  it("shows only the real session account and the returned risk profile", async () => {
    renderPage();

    const account = screen.getByRole("region", { name: "账户信息" });
    expect(within(account).getByText("张三")).toBeInTheDocument();
    expect(within(account).getByText("user@example.com")).toBeInTheDocument();
    expect(within(account).getByText("138****0000")).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "风险档案" })).toHaveTextContent("稳健型");
    expect(mockGetRiskProfile).toHaveBeenCalledTimes(1);
  });

  it("does not request or render personal data before formal authentication", () => {
    renderPage(false);

    expect(screen.getByText(/业务内容已锁定/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "账户信息" })).not.toBeInTheDocument();
    expect(mockGetRiskProfile).not.toHaveBeenCalled();
  });
});
