function knowledgeCategory(item) {
      const key = `${item.original_name || ""} ${item.title || ""}`.toLowerCase();
      if (/evidence-hierarchy|market-causality|market-trend-risk|research-workflows|证据规则|研究工作流/.test(key)) return {key: "method", label: "规则与方法"};
      if (/earnings-quality|financial-drivers|business-structure|filing-evidence|peer-operating|财报|利润|现金流|主营|同行/.test(key)) return {key: "financial", label: "财务与经营"};
      if (/event-timeline|事件脉络|公告/.test(key)) return {key: "event", label: "事件与公告"};
      if (/analyst-expectations|shareholder-structure|分析师|股东/.test(key)) return {key: "ownership", label: "预期与股东"};
      if (/research-archive|research-outcome|research-actions|研究档案|研究结果复盘|研究行动/.test(key)) return {key: "research", label: "研究档案"};
      return {key: "other", label: "其他资料"};
    }

    function knowledgeSymbol(item) {
      return `${item.original_name || ""} ${item.title || ""}`.match(/\b(?:\d{6}\.(?:SZ|SS)|NVDA)\b/i)?.[0]?.toUpperCase() || "";
    }

    async function openKnowledgeDocument(item, button) {
      const original = button.textContent;
      button.disabled = true; button.textContent = "读取中…";
      try {
        const document = await api(`/me/knowledge/${encodeURIComponent(item.id)}`);
        const category = knowledgeCategory(item);
        openReader(document.title || item.title, document.content || "这份资料暂时没有可阅读正文。", `${category.label} · ${item.scope === "user" ? "个人资料" : "通用资料"} · 更新 ${readableTime(item.updated_at)}`);
      } catch (error) {
        openReader(item.title, error?.message || "这份资料暂时无法读取。", "资料读取未完成");
      } finally {
        button.disabled = false; button.textContent = original;
      }
    }

    function renderKnowledge(data = null) {
      if (data) {
        state.knowledge = data.items || [];
        state.knowledgeSummary = data.summary || {};
      }
      renderAgentResearchContext();
      $("knowledgeSummary").textContent = `通用资料 ${state.knowledgeSummary.common || 0} 份 · 个人资料 ${state.knowledgeSummary.user || 0} 份 · Agent 只会检索与当前问题相关的片段`;
      const query = state.knowledgeQuery.trim().toLowerCase();
      const visibleItems = state.knowledge.filter(item => {
        const category = knowledgeCategory(item);
        const haystack = `${item.title || ""} ${item.original_name || ""} ${knowledgeSymbol(item)}`.toLowerCase();
        return (!query || haystack.includes(query))
          && (state.knowledgeScope === "all" || item.scope === state.knowledgeScope)
          && (state.knowledgeType === "all" || category.key === state.knowledgeType);
      });
      $("knowledgeVisibleCount").textContent = `显示 ${visibleItems.length} / ${state.knowledge.length} 份资料`;
      const container = $("knowledgeList"); container.innerHTML = "";
      for (const item of visibleItems) {
        const row = document.createElement("div"); row.className = "knowledge-item";
        const identity = document.createElement("div");
        const title = document.createElement("div"); title.className = "knowledge-item-title"; title.title = item.title; title.textContent = item.title;
        const meta = document.createElement("div"); meta.className = "knowledge-item-meta";
        const symbol = knowledgeSymbol(item);
        meta.textContent = `${item.original_name || "系统生成资料"} · ${numeric(item.content_chars || 0)} 字${symbol ? ` · ${symbol}` : ""}`;
        identity.append(title, meta);
        const category = knowledgeCategory(item);
        const categoryNode = document.createElement("div"); categoryNode.className = "knowledge-category"; categoryNode.textContent = category.label;
        const badge = document.createElement("span"); badge.className = `knowledge-badge${item.scope === "user" ? " user" : ""}`; badge.textContent = item.scope === "user" ? "个人" : "通用";
        const updated = document.createElement("div"); updated.className = "knowledge-updated"; updated.textContent = readableTime(item.updated_at);
        const controls = document.createElement("div"); controls.className = "knowledge-item-controls";
        const read = document.createElement("button"); read.className = "knowledge-read"; read.type = "button"; read.textContent = "查看";
        read.addEventListener("click", () => { void openKnowledgeDocument(item, read); });
        controls.appendChild(read);
        if (item.scope === "user") {
          const remove = document.createElement("button"); remove.className = "knowledge-remove"; remove.type = "button"; remove.title = "删除个人资料"; remove.textContent = "×";
          remove.addEventListener("click", async () => {
            if (!window.confirm(`确定删除“${item.title}”吗？删除后 Agent 将无法再检索这份个人资料。`)) return;
            try { await api(`/me/knowledge/${encodeURIComponent(item.id)}`, {method:"DELETE"}); await loadKnowledge(); }
            catch { addMessage("agent", "这份个人资料暂时无法删除。"); }
          });
          controls.appendChild(remove);
        }
        row.append(identity, categoryNode, badge, updated, controls);
        container.appendChild(row);
      }
      if (!container.children.length) container.innerHTML = '<div class="empty">没有符合当前筛选条件的资料。</div>';
      renderAccountCenter();
    }

    async function loadKnowledge() {
      if (!state.user) return;
      renderKnowledge(await api("/me/knowledge"));
    }

    async function uploadKnowledgeFile(file) {
      if (!file) return;
      $("uploadKnowledge").disabled = true;
      $("uploadKnowledge").textContent = "正在入库…";
      const form = new FormData(); form.append("file", file, file.name);
      try {
        const document = await api("/me/knowledge", {method: "POST", body: form});
        await loadKnowledge();
        addMessage("agent", `已将“${document.title}”加入你的资料库，后续对话会按问题自动检索。`);
      } catch (error) {
        addMessage("agent", error.message || "这份资料暂时无法入库。");
      } finally {
        $("knowledgeInput").value = "";
        $("uploadKnowledge").disabled = false;
        $("uploadKnowledge").textContent = "＋ 添加个人资料";
      }
    }

    async function resolveMemoryCandidate(memoryId, action, card) {
      const buttons = card.querySelectorAll("button");
      buttons.forEach(button => button.disabled = true);
      const status = card.querySelector(".memory-card-status");
      status.textContent = action === "confirm" ? "正在保存个人偏好…" : "正在处理…";
      try {
        await api(`/me/memories/${encodeURIComponent(memoryId)}/${action}`, { method: "POST" });
        card.classList.add("resolved");
        card.querySelector(".memory-card-actions")?.remove();
        status.textContent = action === "confirm"
          ? "已保存为长期偏好，后续研究会结合这条信息。"
          : "本次不保存，不会用于后续研究。";
      } catch {
        status.textContent = "这次操作暂未完成，请重试。";
        buttons.forEach(button => button.disabled = false);
      }
    }

    function renderMemoryCandidate(memory, answer = "") {
      if (answer) addMessage("agent", answer);
      if (!memory?.id || document.querySelector(`[data-memory-id="${memory.id}"]`)) return;
      const card = document.createElement("div");
      card.className = "memory-card";
      card.dataset.memoryId = memory.id;
      const title = document.createElement("div"); title.className = "memory-card-title"; title.textContent = "待确认的个人偏好";
      const content = document.createElement("div"); content.className = "memory-card-content"; content.textContent = memory.content || "";
      const status = document.createElement("div"); status.className = "memory-card-status"; status.textContent = "只有你确认后，它才会用于后续分析。";
      const actions = document.createElement("div"); actions.className = "memory-card-actions";
      const confirm = document.createElement("button"); confirm.className = "btn primary"; confirm.textContent = "确认保存";
      const reject = document.createElement("button"); reject.className = "btn"; reject.textContent = "暂不保存";
      confirm.addEventListener("click", () => resolveMemoryCandidate(memory.id, "confirm", card));
      reject.addEventListener("click", () => resolveMemoryCandidate(memory.id, "reject", card));
      actions.append(confirm, reject); card.append(title, content, status, actions); $("messages").appendChild(card);
      $("messages").scrollTop = $("messages").scrollHeight;
    }

    async function loadMemoryCandidates() {
      if (!state.user) return;
      try {
        const data = await api("/me/memories?status=candidate");
        for (const memory of (data.items || []).slice(0, 3).reverse()) renderMemoryCandidate(memory);
      } catch { /* session recovery is handled by ensureUser */ }
    }
