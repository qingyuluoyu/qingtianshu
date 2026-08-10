import { api } from "../../api/client";

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

// ---------- 风险档案 ----------

export type RiskProfile = {
  id: string | null;
  status: string | null;
  riskLevel: string | null;
  riskLabel: string | null;
  score: number | null;
  answers: Record<string, unknown>;
  confirmedAt: string | null;
  draftUpdatedAt: string | null;
  boundary: string | null;
};

export async function getRiskProfile(): Promise<RiskProfile | null> {
  const { data, error, response } = await api.GET("/me/risk-profile");
  if (!response.ok || error || data === undefined) {
    throw new Error(`风险档案请求失败 (${response.status})`);
  }
  const root = asRecord(data);
  const profile = asRecord(root?.profile);
  if (!profile) return null;
  return {
    id: asString(profile.id),
    status: asString(profile.status),
    riskLevel: asString(profile.risk_level ?? profile.riskLevel),
    riskLabel: asString(profile.risk_label ?? profile.riskLabel),
    score: asNumber(profile.score),
    answers: (profile.answers && typeof profile.answers === "object") ? profile.answers as Record<string, unknown> : {},
    confirmedAt: asString(profile.confirmed_at ?? profile.confirmedAt),
    draftUpdatedAt: asString(profile.draft_updated_at ?? profile.draftUpdatedAt),
    boundary: asString(profile.boundary),
  };
}

export async function saveRiskProfileDraft(answers: Record<string, unknown>): Promise<boolean> {
  const { error, response } = await api.PUT("/me/risk-profile/draft", {
    body: { answers } as unknown as never,
  });
  return response.ok && !error;
}

export async function confirmRiskProfile(): Promise<RiskProfile | null> {
  const { data, error, response } = await api.POST("/me/risk-profile/confirm", { body: {} as never });
  if (!response.ok || error || data === undefined) return null;
  const root = asRecord(data);
  const profile = asRecord(root?.profile);
  if (!profile) return null;
  return {
    id: asString(profile.id),
    status: asString(profile.status),
    riskLevel: asString(profile.risk_level ?? profile.riskLevel),
    riskLabel: asString(profile.risk_label ?? profile.riskLabel),
    score: asNumber(profile.score),
    answers: (profile.answers && typeof profile.answers === "object") ? profile.answers as Record<string, unknown> : {},
    confirmedAt: asString(profile.confirmed_at ?? profile.confirmedAt),
    draftUpdatedAt: asString(profile.draft_updated_at ?? profile.draftUpdatedAt),
    boundary: asString(profile.boundary),
  };
}
