import styles from "./PlaceholderPage.module.css";

export function PlaceholderPage({ title, responsibility, locked }: { title: string; responsibility: string; locked: boolean }) {
  return (
    <section className={styles.card} aria-live="polite">
      <p className={styles.eyebrow}>{locked ? "需要正式账户" : "正式页面底座"}</p>
      <h1>{title}</h1>
      <p>{responsibility}</p>
      <div className={styles.state}>{locked ? "业务内容已锁定，请先登录或注册。" : "建设中：本轮不接入业务数据。"}</div>
    </section>
  );
}
