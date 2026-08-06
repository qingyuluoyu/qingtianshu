import { ModuleState } from "../../../components/workbench/ModuleState";
import type { AdvisorCitation, EvidenceSource } from "../adapters";
import styles from "../AdvisorPage.module.css";

export function EvidenceDrawer({ citations, sources }: { citations: AdvisorCitation[]; sources: EvidenceSource[] }) {
  if (citations.length === 0 && sources.length === 0) {
    return <ModuleState detail="只有后端返回可追溯证据时才会在这里展示；不会补造评分或来源。" state="empty" title="本轮暂无结构化证据" />;
  }
  return (
    <section aria-label="本轮证据" className={styles.evidenceList}>
      {citations.map((citation) => (
        <article className={styles.evidenceCard} key={citation.id}>
          <div className={styles.evidenceHeader}>
            <strong>{citation.sourceName}</strong>
            <span>{citation.evidenceType ?? "证据"}</span>
          </div>
          {citation.excerpt ? <p>{citation.excerpt}</p> : null}
          {citation.dataTime || citation.reportPeriod ? <small>{[citation.dataTime, citation.reportPeriod].filter(Boolean).join(" · ")}</small> : null}
          {citation.limitations.length > 0 ? <ul>{citation.limitations.map((item) => <li key={item}>{item}</li>)}</ul> : null}
          {citation.sourceUrl ? <a href={citation.sourceUrl} rel="noreferrer" target="_blank">打开来源</a> : null}
        </article>
      ))}
      {sources.filter((source) => !citations.some((citation) => citation.sourceName === source.title)).map((source) => (
        <article className={styles.evidenceCard} key={`${source.kind ?? "source"}-${source.title}`}>
          <div className={styles.evidenceHeader}><strong>{source.title}</strong><span>{source.kind ?? "证据"}</span></div>
          {source.copy ? <p>{source.copy}</p> : null}
          {source.meta ? <small>{source.meta}</small> : null}
          {source.url ? <a href={source.url} rel="noreferrer" target="_blank">打开来源</a> : null}
        </article>
      ))}
    </section>
  );
}
