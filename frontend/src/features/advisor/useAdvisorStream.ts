import { useCallback, useEffect, useRef, useState } from "react";
import {
  parseAdvisorCitation,
  parseWritebackCandidate,
  type AdvisorChatAccepted,
  type AdvisorCitation,
  type WritebackCandidate,
} from "./adapters";

export type AdvisorStreamState = {
  requestId: string | null;
  status: "idle" | "connecting" | "streaming" | "reconnecting" | "completed" | "error";
  label: string | null;
  draft: string;
  citations: AdvisorCitation[];
  candidates: WritebackCandidate[];
  runId: string | null;
  error: string | null;
};

const initialState: AdvisorStreamState = {
  requestId: null,
  status: "idle",
  label: null,
  draft: "",
  citations: [],
  candidates: [],
  runId: null,
  error: null,
};

function mergeById<T extends { id: string }>(items: T[], next: T): T[] {
  const index = items.findIndex((item) => item.id === next.id);
  if (index < 0) return [...items, next];
  return items.map((item, itemIndex) => itemIndex === index ? next : item);
}

export function useAdvisorStream() {
  const sourceRef = useRef<EventSource | null>(null);
  const terminalRef = useRef(false);
  const [state, setState] = useState<AdvisorStreamState>(initialState);

  const close = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
  }, []);

  const start = useCallback((requestId: string) => {
    close();
    terminalRef.current = false;
    setState({ ...initialState, requestId, status: "connecting", label: "正在建立私有回答连接…" });
    const source = new EventSource(`/me/chat/stream/${encodeURIComponent(requestId)}`);
    sourceRef.current = source;
    source.onopen = () => {
      setState((current) => ({ ...current, status: "streaming", label: current.label ?? "正在读取研究证据…" }));
    };
    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as Record<string, unknown>;
        const type = typeof payload.type === "string" ? payload.type : "";
        if (type === "agent_progress") {
          setState((current) => ({
            ...current,
            status: "streaming",
            label: typeof payload.label === "string" ? payload.label : current.label,
          }));
        } else if (type === "agent_delta") {
          const draft = typeof payload.draft === "string" ? payload.draft : "";
          const safeToShow = payload.is_guarded_partial === true
            || payload.is_unverified === false
            || payload.is_final === true;
          setState((current) => ({
            ...current,
            status: "streaming",
            draft: safeToShow ? draft : current.draft,
            label: safeToShow ? "正在生成 · 已显示目前可确认的内容" : "回答草稿已生成，正在核对数字与证据…",
          }));
        } else if (type === "agent_stream_status") {
          setState((current) => ({
            ...current,
            draft: payload.reset === true ? "" : current.draft,
            label: typeof payload.label === "string" ? payload.label : current.label,
          }));
        } else if (type === "agent_citation") {
          const citation = parseAdvisorCitation(payload.citation);
          if (citation) setState((current) => ({ ...current, citations: mergeById(current.citations, citation) }));
        } else if (type === "agent_writeback_candidate") {
          const candidate = parseWritebackCandidate(payload.candidate);
          setState((current) => ({ ...current, candidates: mergeById(current.candidates, candidate) }));
        } else if (type === "agent_structured_failed") {
          setState((current) => ({ ...current, label: "回答已完成，结构化证据暂时不可用。" }));
        } else if (type === "agent_stream_complete" || type === "agent_stream_error") {
          terminalRef.current = true;
          close();
          setState((current) => ({
            ...current,
            status: type === "agent_stream_complete" ? "completed" : "error",
            runId: typeof payload.run_id === "string" ? payload.run_id : current.runId,
            label: type === "agent_stream_complete" ? "回答已完成并保存。" : "实时连接已结束。",
          }));
        }
      } catch {
        // A malformed private event must not hide the final HTTP response.
      }
    };
    source.onerror = () => {
      if (terminalRef.current) return;
      setState((current) => ({ ...current, status: "reconnecting", label: "实时连接中断，正在等待最终回答…" }));
    };
  }, [close]);

  const finish = useCallback((response: AdvisorChatAccepted) => {
    terminalRef.current = true;
    close();
    setState((current) => ({
      ...current,
      status: "completed",
      label: "回答已完成并保存。",
      draft: response.answer,
      runId: response.runId,
      citations: response.structuredAnswer?.citations ?? current.citations,
      candidates: response.structuredAnswer?.candidateWritebacks ?? current.candidates,
      error: null,
    }));
  }, [close]);

  const fail = useCallback((message: string) => {
    terminalRef.current = true;
    close();
    setState((current) => ({ ...current, status: "error", label: null, error: message }));
  }, [close]);

  const reset = useCallback(() => {
    terminalRef.current = true;
    close();
    setState(initialState);
  }, [close]);

  useEffect(() => close, [close]);

  return { state, start, finish, fail, reset };
}
