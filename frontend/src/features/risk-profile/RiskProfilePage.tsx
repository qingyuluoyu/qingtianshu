import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { confirmRiskProfile, getRiskProfile, saveRiskProfileDraft } from "./api";
import { riskProfileQueries } from "./queries";
import styles from "./RiskProfilePage.module.css";

const RISK_LEVELS = [
  { key: "conservative", label: "保守型", desc: "优先保本，接受较低收益。" },
  { key: "balanced", label: "平衡型", desc: "兼顾收益与风险，适度波动。" },
  { key: "growth", label: "成长型", desc: "追求较高收益，能承受较大波动。" },
  { key: "aggressive", label: "进取型", desc: "最大化收益，接受高风险。" },
];

type Props = { authenticated: boolean };

export function RiskProfilePage({ authenticated }: Props) {
  const queryClient = useQueryClient();
  const profile = useQuery(riskProfileQueries.profile());
  const [draft, setDraft] = useState<string>("balanced");
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const confirmed = profile.data?.status === "confirmed" || profile.data?.status === "active";
  const currentLevel = profile.data?.riskLevel ?? draft;

  const levelInfo = useMemo(
    () => RISK_LEVELS.find((l) => l.key === currentLevel) ?? RISK_LEVELS[1],
    [currentLevel],
  );

  const handleSaveDraft = async () => {
    setSaving(true);
    setMessage(null);
    const ok = await saveRiskProfileDraft({ risk_level: draft });
    if (ok) {
      setMessage("草稿已保存");
      await queryClient.invalidateQueries({ queryKey: ["risk-profile"] });
    } else {
      setMessage("保存失败，请重试");
    }
    setSaving(false);
  };

  const handleConfirm = async () => {
    setConfirming(true);
    setMessage(null);
    const result = await confirmRiskProfile();
    if (result) {
      setMessage("风险档案已确认");
      await queryClient.invalidateQueries({ queryKey: ["risk-profile"] });
    } else {
      setMessage("确认失败，请重试");
    }
    setConfirming(false);
  };

  return (
    <div className={styles.page}>
      <header className={styles.hero}>
        <div>
          <h1>风险档案</h1>
          <p>管理您的风险偏好，获取与您风险承受能力匹配的投资建议。</p>
        </div>
      </header>

      {profile.isPending ? (
        <div className={styles.loading}>正在读取风险档案…</div>
      ) : profile.isError ? (
        <div className={styles.error} role="status">
          <span>风险档案暂时不可用。</span>
          <button onClick={() => void profile.refetch()} type="button">重新读取</button>
        </div>
      ) : confirmed ? (
        <section className={styles.confirmed}>
          <div className={styles.badge}>已确认</div>
          <h2>当前风险等级：{levelInfo.label}</h2>
          <p>{levelInfo.desc}</p>
          <p className={styles.meta}>
            风险分数：{profile.data?.score ?? "—"} ·
            确认时间：{profile.data?.confirmedAt ? new Date(profile.data.confirmedAt).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" }) : "—"}
          </p>
        </section>
      ) : (
        <section className={styles.form}>
          <h2>选择您的风险偏好</h2>
          <div className={styles.levels}>
            {RISK_LEVELS.map((level) => (
              <button
                aria-pressed={draft === level.key}
                className={`${styles.levelCard} ${draft === level.key ? styles.levelActive : ""}`}
                key={level.key}
                onClick={() => setDraft(level.key)}
                type="button"
              >
                <strong>{level.label}</strong>
                <span>{level.desc}</span>
              </button>
            ))}
          </div>

          <div className={styles.actions}>
            <button className={styles.primary} disabled={saving} onClick={handleSaveDraft} type="button">
              {saving ? "保存中…" : "保存草稿"}
            </button>
            <button className={styles.secondary} disabled={confirming} onClick={handleConfirm} type="button">
              {confirming ? "确认中…" : "确认并生效"}
            </button>
          </div>
        </section>
      )}

      {message ? (
        <div className={styles.message} role="status">{message}</div>
      ) : null}
    </div>
  );
}
