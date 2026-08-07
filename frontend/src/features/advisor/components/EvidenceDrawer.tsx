import { useState } from "react";
import { ModuleState } from "../../../components/workbench/ModuleState";
import type { AdvisorCitation, EvidenceSource } from "../adapters";
import styles from "../AdvisorPage.module.css";

const COLLAPSED_EVIDENCE_COUNT = 10;

export function EvidenceDrawer({ citations, sources }: { citations: AdvisorCitation[]; sources: EvidenceSource[] }) {
  const [expanded, setExpanded] = useState(false);
  if (citations.length === 0 && sources.length === 0) {
    return <ModuleState detail="只有后端返回可追溯证据时才会在这里展示；不会补造评分或来源。" state="empty" title="本轮暂无结构化证据" />;
  }
  const uniqueSources = sources.filter((source) => !citations.some((citation) => citation.sourceName === source.title));
  const cards = [
    ...citations.map((citation) => (
      <article className={styles.evidenceCard} key={`citation-${citation.id}`}>
        <div className={styles.evidenceHeader}>
          <strong>{citation.sourceName}</strong>
          <span>{citation.evidenceType ?? "证据"}</span>
        </div>
        {citation.excerpt ? <p>{citation.excerpt}</p> : null}
        {citation.dataTime || citation.reportPeriod ? <small>{[citation.dataTime, citation.reportPeriod].filter(Boolean).join(" · ")}</small> : null}
        {citation.limitations.length > 0 ? <ul>{citation.limitations.map((item) => <li key={item}>{item}</li>)}</ul> : null}
        {citation.sourceUrl ? <a href={citation.sourceUrl} rel="noreferrer" target="_blank">打开来源</a> : null}
      </article>
    )),
    ...uniqueSources.map((source) => (
      <article className={styles.evidenceCard} key={`${source.kind ?? "source"}-${source.title}`}>
        <div className={styles.evidenceHeader}><strong>{source.title}</strong><span>{source.kind ?? "证据"}</span></div>
        {source.copy ? <p>{source.copy}</p> : null}
        {source.meta ? <small>{source.meta}</small> : null}
        {source.url ? <a href={source.url} rel="noreferrer" target="_blank">打开来源</a> : null}
      </article>
    )),
  ];
  const visibleCards = expanded ? cards : cards.slice(0, COLLAPSED_EVIDENCE_COUNT);
  return (
    <section aria-label="本轮证据" className={styles.evidenceList}>
      {cards.length > COLLAPSED_EVIDENCE_COUNT ? (
        <div className={styles.evidenceControls}>
          <span>{expanded ? `已展示全部 ${cards.length} 条` : `优先展示 ${COLLAPSED_EVIDENCE_COUNT} / ${cards.length} 条`}</span>
          <button aria-expanded={expanded} onClick={() => setExpanded((value) => !value)} type="button">
            {expanded ? "收起" : `查看全部 ${cards.length} 条`}
          </button>
        </div>
      ) : null}
      {visibleCards}
    </section>
  );
}
