(() => {
  const messages = document.querySelector("#messages");
  const context = document.querySelector("#context");
  const form = document.querySelector("#chat-form");
  const input = document.querySelector("#question");
  let conversationId = null;
  const addMessage = (role, text) => { const node = document.createElement("article"); node.className = `message ${role}`; node.textContent = text; messages.append(node); messages.scrollTop = messages.scrollHeight; };
  const renderSection = (title, value) => { const details = document.createElement("details"); details.open = true; const summary = document.createElement("summary"); summary.textContent = title; const body = document.createElement("pre"); body.textContent = JSON.stringify(value, null, 2); details.append(summary, body); return details; };
  const renderContext = snapshot => { context.textContent = ""; [["问题识别", snapshot.routing], ["实际带入的背景", snapshot.actual_context], ["证据与缺口", snapshot.evidence], ["可用但未采用 / 安全边界", snapshot.excluded_or_blocked], ["执行记录", snapshot.execution]].forEach(([title, value]) => context.append(renderSection(title, value))); };
  form.addEventListener("submit", async event => { event.preventDefault(); const message = input.value.trim(); if (!message) return; input.value = ""; addMessage("user", message); const response = await fetch("/me/advisor-lab/chat", { method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json"}, body: JSON.stringify({message, conversation_id: conversationId, request_id: crypto.randomUUID()}) }); const data = await response.json(); if (!response.ok) { addMessage("assistant", data.detail || "请求失败"); return; } conversationId = data.conversation_id || conversationId; addMessage("assistant", data.answer || "未返回回答"); if (data.assistant_message_id) { const snapshotResponse = await fetch(`/me/advisor-lab/context/${encodeURIComponent(data.assistant_message_id)}`, {credentials: "same-origin"}); if (snapshotResponse.ok) renderContext(await snapshotResponse.json()); } });
})();
