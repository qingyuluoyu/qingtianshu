import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { AuthSession } from "../../api/session";
import { confirmRiskProfile, getRiskProfile, saveRiskProfileDraft } from "./api";
import { riskProfileQueries } from "./queries";
import styles from "./RiskProfilePage.module.css";

const RISK_LEVELS = [
  { key: "conservative", label: "保守型", desc: "优先保本，接受较低收益。" },
  { key: "balanced", label: "平衡型", desc: "兼顾收益与风险，适度波动。" },
  { key: "growth", label: "成长型", desc: "追求较高收益，能承受较大波动。" },
  { key: "aggressive", label: "进取型", desc: "最大化收益，接受高风险。" },
];

type Props = {
  authenticated: boolean;
  session: AuthSession | null;
};

export function RiskProfilePage({ authenticated, session }: Props) {
  const queryClient = useQueryClient();
  const profile = useQuery({ ...riskProfileQueries.profile(), enabled: authenticated });
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

  if (!authenticated) {
    return (
      <div className={styles.page}>
        <header className={styles.hero}>
          <div>
            <h1>个人中心</h1>
            <p>账户与风险档案仅在正式登录后读取和展示。</p>
          </div>
        </header>
        <section aria-label="个人中心访问限制" className={styles.error}>
          <span>业务内容已锁定，请先登录或注册。</span>
          <span>登录后可查看真实账户信息与已保存的风险档案。</span>
        </section>
      </div>
    );
  }

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
          <h1>个人中心</h1>
          <p>账户身份和风险档案均来自当前正式会话与已保存记录，不展示估算资产或模拟风险数据。</p>
        </div>
      </header>

      <section aria-label="账户信息" className={styles.account}>
        <div className={styles.accountHeading}>
          <h2>正式账户</h2>
          <span>当前会话</span>
        </div>
        <dl className={styles.accountDetails}>
          <div><dt>姓名</dt><dd>{session?.name ?? "—"}</dd></div>
          <div><dt>账号</dt><dd>{session?.account ?? "—"}</dd></div>
          <div><dt>已验证手机号</dt><dd>{session?.masked_phone ?? "—"}</dd></div>
          <div><dt>会话有效期</dt><dd>{session?.session_expires_at ? new Date(session.session_expires_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" }) : "—"}</dd></div>
        </dl>
      </section>

      {profile.isPending ? (
        <div className={styles.loading}>正在读取风险档案…</div>
      ) : profile.isError ? (
        <div className={styles.error} role="status">
          <span>风险档案暂时不可用。</span>
          <button onClick={() => void profile.refetch()} type="button">重新读取</button>
        </div>
      ) : confirmed ? (
        <section aria-label="风险档案" className={styles.confirmed}>
          <div className={styles.badge}>已确认</div>
          <h2>当前风险等级：{profile.data?.riskLabel ?? levelInfo.label}</h2>
          <p>{levelInfo.desc}</p>
          <p className={styles.meta}>
            风险分数：{profile.data?.score ?? "—"} ·
            确认时间：{profile.data?.confirmedAt ? new Date(profile.data.confirmedAt).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" }) : "—"}
          </p>
          {profile.data?.boundary ? <p className={styles.boundary}>{profile.data.boundary}</p> : null}
        </section>
      ) : (
        <section aria-label="风险档案" className={styles.form}>
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
