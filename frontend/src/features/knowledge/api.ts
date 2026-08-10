import { api } from "../../api/client";
import { requestError } from "../../api/requestError";

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

// ---------- 知识库 ----------

export type KnowledgeDocument = {
  id: string;
  title: string;
  category: string | null;
  source: string | null;
  status: string | null;
  chunkCount: number | null;
  createdAt: string | null;
  contentPreview: string | null;
};

export async function listKnowledgeDocuments(): Promise<KnowledgeDocument[]> {
  const { data, error, response } = await api.GET("/me/knowledge");
  if (!response.ok || error || data === undefined) throw requestError("知识库列表", response.status);
  const root = asRecord(data);
  const items = Array.isArray(root?.items) ? root.items : [];
  return items.flatMap((raw) => {
    const item = asRecord(raw);
    if (!item) return [];
    return [{
      id: asString(item.id) ?? "",
      title: asString(item.title) ?? "",
      category: asString(item.category),
      source: asString(item.source),
      status: asString(item.status),
      chunkCount: asNumber(item.chunk_count ?? item.chunkCount),
      createdAt: asString(item.created_at ?? item.createdAt),
      contentPreview: asString(item.content_preview ?? item.contentPreview ?? item.summary),
    }];
  });
}

export async function getKnowledgeDocument(id: string): Promise<KnowledgeDocument | null> {
  const { data, error, response } = await api.GET("/me/knowledge/{document_id}", {
    params: { path: { document_id: id } },
  });
  if (!response.ok || error || data === undefined) throw requestError("知识库详情", response.status);
  const root = asRecord(data);
  if (!root) return null;
  return {
    id: asString(root.id) ?? id,
    title: asString(root.title) ?? "",
    category: asString(root.category),
    source: asString(root.source),
    status: asString(root.status),
    chunkCount: asNumber(root.chunk_count ?? root.chunkCount),
    createdAt: asString(root.created_at ?? root.createdAt),
    contentPreview: asString(root.content_preview ?? root.contentPreview ?? root.content),
  };
}

export async function uploadKnowledgeDocument(title: string, file: File): Promise<KnowledgeDocument | null> {
  const form = new FormData();
  form.append("title", title);
  form.append("file", file);
  const response = await fetch("/me/knowledge", {
    body: form,
    credentials: "same-origin",
    method: "POST",
  });
  if (!response.ok) throw new Error(`个人资料上传请求失败 (${response.status})`);
  const root = asRecord(await response.json());
  const doc = asRecord(root?.document ?? root);
  if (!doc) return null;
  return {
    id: asString(doc.id) ?? "",
    title: asString(doc.title) ?? title,
    category: asString(doc.category),
    source: asString(doc.source),
    status: asString(doc.status),
    chunkCount: asNumber(doc.chunk_count ?? doc.chunkCount),
    createdAt: asString(doc.created_at ?? doc.createdAt),
    contentPreview: asString(doc.content_preview ?? doc.contentPreview),
  };
}

export async function deleteKnowledgeDocument(id: string): Promise<boolean> {
  const { response, error } = await api.DELETE("/me/knowledge/{document_id}", {
    params: { path: { document_id: id } },
  });
  if (!response.ok || error) throw requestError("删除知识库资料", response.status);
  return true;
}
