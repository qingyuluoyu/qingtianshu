function refreshDeepStockSymbolOptions() {
      const select = $("deepStockSymbol");
      if (!select) return;
      const selected = select.value;
      const known = new Map([
        ["000063.SZ", "中兴通讯"],
        ["300308.SZ", "中际旭创"],
        ["NVDA", "英伟达"]
      ]);
      for (const item of state.watchlist || []) known.set(item.symbol, item.name || item.symbol);
      for (const item of state.deepStockSessions || []) known.set(item.symbol, item.name || item.symbol);
      select.innerHTML = "";
      for (const [symbol, name] of known) {
        const option = document.createElement("option");
        option.value = symbol;
        option.textContent = `${name} · ${symbol}`;
        select.appendChild(option);
      }
      if ([...known.keys()].includes(selected)) select.value = selected;
    }

    async function optionalApi(path) {
      try { return await api(path); }
      catch { return null; }
    }

    async function apiResult(path) {
      try {
        return {ok: true, value: await api(path), error: null};
      } catch (error) {
        return {
          ok: false,
          value: null,
          error: {
            status: error?.status || null,
            message: error?.message || ""
          }
        };
      }
    }

    function structuredItemText(item) {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object") return "";
      const title = item.title || item.label || item.name || item.account_label || item.event_type_label;
      const detail = item.summary || item.detail || item.statement || item.effect || item.explanation || item.current_value_text;
      if (title && detail && !String(detail).startsWith(String(title))) return `${title}：${detail}`;
      return String(detail || title || "");
    }

    function appendDeepInfoCard(container, {title, meta = "", copy = "", items = []}) {
      const meaningfulItems = items.map(structuredItemText).filter(Boolean);
      if (!copy && !meaningfulItems.length) return;
      const card = document.createElement("section"); card.className = "deep-info-card";
      const head = document.createElement("div"); head.className = "deep-info-head";
      const titleNode = document.createElement("div"); titleNode.className = "deep-info-title"; titleNode.textContent = title;
      const detail = document.createElement("button"); detail.type = "button"; detail.className = "deep-info-detail"; detail.textContent = "详细资料";
      detail.addEventListener("click", () => {
        const sections = [];
        if (copy) sections.push(copy);
        if (meaningfulItems.length) sections.push(meaningfulItems.map((text, index) => `${index + 1}. ${text}`).join("\n\n"));
        openReader(title, sections.join("\n\n"), meta || "结构化研究资料");
      });
      head.append(titleNode, detail); card.appendChild(head);
      if (meta) { const metaNode = document.createElement("div"); metaNode.className = "deep-info-meta"; metaNode.textContent = meta; card.appendChild(metaNode); }
      if (copy) { const copyNode = document.createElement("div"); copyNode.className = "deep-info-copy"; copyNode.textContent = copy; card.appendChild(copyNode); }
      if (meaningfulItems.length) {
        const list = document.createElement("ul"); list.className = "deep-info-list";
        for (const text of meaningfulItems.slice(0, 4)) { const item = document.createElement("li"); item.textContent = text; list.appendChild(item); }
        card.appendChild(list);
      }
      container.appendChild(card);
    }

    function appendDeepBoardCard(container, {kind, title, items = [], previewLimit = 3}) {
      const normalized = items.map(structuredItemText).filter(Boolean);
      const previewItems = normalized.slice(0, previewLimit);
      const card = document.createElement("section"); card.className = `deep-board-card ${kind}`;
      const head = document.createElement("div"); head.className = "deep-board-head";
      const titleNode = document.createElement("div"); titleNode.className = "deep-board-title"; titleNode.textContent = title;
      const count = document.createElement("span"); count.className = "deep-board-count"; count.textContent = `${normalized.length} 项`;
      const headActions = document.createElement("div"); headActions.className = "deep-board-head-actions";
      headActions.appendChild(count);
      if (normalized.length) {
        const detail = document.createElement("button"); detail.type = "button"; detail.className = "deep-board-detail"; detail.textContent = "查看全部";
        detail.addEventListener("click", () => openReader(
          title,
          normalized.map((text, index) => `${index + 1}. ${text}`).join("\n\n"),
          `结构化证据 ${normalized.length} 项 · 点击外部或关闭按钮返回`
        ));
        headActions.appendChild(detail);
      }
      head.append(titleNode, headActions); card.appendChild(head);
      const list = document.createElement("ul"); list.className = "deep-board-list";
      for (const text of previewItems.length ? previewItems : ["当前没有可确定展示的结构化证据。"] ) {
        const item = document.createElement("li"); item.textContent = text; list.appendChild(item);
      }
      card.appendChild(list); container.appendChild(card);
    }

    function researchClaimText(item) {
      if (!item) return "";
      const coverageLabels = {sufficient: "来源与时间较完整", partial: "部分覆盖", insufficient: "弱证据线索", unavailable: "暂不可用"};
      const evidence = item.evidence_summary ? `；依据：${item.evidence_summary}` : "";
      const source = item.source_name ? `；来源：${item.source_name}` : "";
      const dataTimeLabel = /^\d{4}-\d{2}-\d{2}$/.test(String(item.data_time || "")) ? item.data_time : readableTime(item.data_time);
      const dataTime = item.data_time ? `；数据时间：${dataTimeLabel}` : "";
      const coverage = item.coverage_status ? `；${coverageLabels[item.coverage_status] || "待核验"}` : "";
      const limitation = item.limitations?.[0] ? `；边界：${item.limitations[0]}` : "";
      return `${item.claim || "未命名研究主张"}${evidence}${source}${dataTime}${coverage}${limitation}`;
    }

    function invalidationConditionText(item) {
      if (!item) return "";
      return `${item.label ? `${item.label}：` : ""}${item.condition || "条件待明确"}${item.meaning ? `；含义：${item.meaning}` : ""}`;
    }

    function latestFinancialMetrics(fundamentals) {
      const report = fundamentals?.summary?.latest_report || fundamentals?.financial_periods?.[0] || {};
      return [
        ["营收同比", report.revenue_yoy_pct == null ? "—" : pct(report.revenue_yoy_pct)],
        ["净利润同比", report.net_profit_yoy_pct == null ? "—" : pct(report.net_profit_yoy_pct)],
        ["毛利率", report.gross_margin_pct == null ? "—" : `${numeric(report.gross_margin_pct)}%`],
        ["现金流/净利润", numeric(fundamentals?.summary?.operating_cashflow_to_net_profit)],
        ["资产负债率", report.debt_asset_ratio_pct == null ? "—" : `${numeric(report.debt_asset_ratio_pct)}%`],
        ["ROE", report.roe_weighted_pct == null ? "—" : `${numeric(report.roe_weighted_pct)}%`]
      ];
    }

    function activateStockSpaceTab(tabKey = "overview", options = {}) {
      const allowed = new Set(["overview", "ai", "evidence", "tasks", "history"]);
      if (!allowed.has(tabKey)) tabKey = "overview";
      state.stockSpaceTab = tabKey;
      const panel = $("deepStockPanel") || document;
      panel.querySelectorAll("[data-stock-space-tab]").forEach(button => {
        const active = button.dataset.stockSpaceTab === tabKey;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
        button.tabIndex = active ? 0 : -1;
      });
      panel.querySelectorAll("[data-stock-space-pane]").forEach(pane => {
        pane.hidden = pane.dataset.stockSpacePane !== tabKey;
      });
      syncAgentPlacement();
      if (typeof syncBoundStockQuickActions === "function") {
        syncBoundStockQuickActions(state.deepStock);
      }
      if (
        tabKey === "ai"
        && state.workspacePage === "deep_stock"
        && state.deepStock?.conversation_id
        && state.conversationId !== state.deepStock.conversation_id
      ) {
        void openBoundStockConversation();
      }
      if (state.workspacePage === "deep_stock") syncWorkspaceUrl(options.historyMode || "none");
    }

    function appendStockWorkspaceItem(container, title, meta = "", detail = null) {
      const interactive = Boolean(detail?.body || detail?.url || detail?.linkId || detail?.onOpen);
      const item = document.createElement(interactive ? "button" : "div"); item.className = `stock-workspace-item${interactive ? " interactive" : ""}`;
      if (interactive) item.type = "button";
      const titleNode = document.createElement("strong"); titleNode.textContent = title;
      item.appendChild(titleNode);
      if (meta) { const metaNode = document.createElement("span"); metaNode.textContent = meta; item.appendChild(metaNode); }
      if (interactive) {
        const affordance = document.createElement("span"); affordance.className = "stock-workspace-item-detail"; affordance.textContent = detail.label || "查看依据与原文";
        item.appendChild(affordance);
        item.setAttribute("aria-label", `${title}，${affordance.textContent}`);
        item.addEventListener("click", () => {
          if (detail.onOpen) detail.onOpen();
          else if (detail.linkId) void openChangeEvent(detail.linkId);
          else openReader(title, detail.body || meta, detail.meta || meta, detail.url || "");
        });
      }
      container.appendChild(item);
    }

    function stockSpaceChangeItems(events, information) {
      const official = (events?.recent_official_events || events?.events || []).map(item => ({
        title: item.title || item.label || "公司披露更新",
        meta: `${item.event_date || item.published_at || "日期待确认"} · ${item.evidence_label || "公司或监管披露"}`,
        url: item.url,
        detail: [
          `证据层级：${item.evidence_label || "公司或监管披露"}`,
          `事件分类：${item.event_label || item.event_type || "待分类"}`,
          `研究相关性：${item.research_relevance_label || "需要结合原判断复核"}`,
          `事件状态：${{confirmed_disclosure: "已确认披露"}[item.event_status] || "已收录，等待阅读原文"}`,
          "处理原则：先阅读官方原文，再判断它是否改变当前关注理由；标题本身不等于影响已经被证实。"
        ].join("\n\n")
      }));
      const announcements = (information?.announcements || []).map(item => ({
        title: item.title || "公司公告更新",
        meta: `${readableTime(item.published_at)} · 公告`,
        url: item.url,
        detail: [
          `来源：${item.source || "公司公告"}`,
          `发布时间：${readableTime(item.published_at)}`,
          item.summary || "公司公告属于优先核验的事实来源。",
          "下一步：阅读原文中的具体金额、时间、对象和适用范围，再与当前判断逐项对照。"
        ].filter(Boolean).join("\n\n")
      }));
      const news = (information?.news || []).map(item => ({
        title: item.title || "市场信息更新",
        meta: `${readableTime(item.published_at)} · 媒体线索，需与正式披露交叉核验`,
        url: item.url,
        detail: [
          `来源：${item.source || "媒体信息"}`,
          `发布时间：${readableTime(item.published_at)}`,
          item.summary || "当前只有媒体标题或摘要，不能直接写成公司已确认的因果。",
          "下一步：寻找公司公告、监管文件或第二个独立信息源交叉确认。"
        ].filter(Boolean).join("\n\n")
      }));
      const seen = new Set();
      return [...official, ...announcements, ...news].filter(item => {
        const key = item.title.trim();
        if (!key || seen.has(key)) return false;
        seen.add(key); return true;
      }).slice(0, 3);
    }

    function workspaceChangeItems(changes) {
      const severityLabels = {attention: "需要优先复核", notice: "发现新变化", stable: "研究基线"};
      return (changes || []).map(change => {
        const verifiedEvent = change.source_type === "verified_change_event" || Boolean(change.link_id);
        const details = [
          change.fact_summary || change.summary,
          verifiedEvent && change.event_type_label ? `事件类型：${change.event_type_label}` : "",
          verifiedEvent && change.source_name ? `来源：${change.source_name}` : "",
          ...(change.changes || []).map(item => item.detail || item.title),
          ...(change.new_evidence || []).map(item => `${item.category_label || "新增证据"}：${item.title}`),
          change.boundary
        ].filter(Boolean);
        return {
          title: change.title || change.summary || "研究证据发生变化",
          meta: [
            readableTime(change.data_as_of || change.created_at),
            change.relevance_status_label,
            change.data_status_label,
            severityLabels[change.severity]
          ].filter(Boolean).join(" · "),
          detail: details.join("\n\n"),
          url: change.source_url || change.url,
          linkId: change.link_id
        };
      }).slice(0, 3);
    }

    function researchActionDetail(action) {
      if (!action) return "当前还没有结构化任务依据。";
      const checks = (action.checks || []).filter(Boolean);
      return [
        `触发条件：${action.condition || "待明确"}`,
        `当前证据：${action.current_evidence || "待补充"}`,
        `下一动作：${action.next_step || "继续核验相关证据"}`,
        checks.length ? `逐项检查：\n${checks.map((item, index) => `${index + 1}. ${item}`).join("\n")}` : ""
      ].filter(Boolean).join("\n\n");
    }

    function observationTaskHistoryDetail(task) {
      const history = task?.history || [];
      const historyLines = history.map(item => {
        const from = item.from_status_label ? `${item.from_status_label} → ` : "";
        return `版本 ${item.version} · ${readableTime(item.created_at)}\n${from}${item.to_status_label || item.to_status || "状态更新"}`;
      });
      return [
        `任务说明：${task?.description || "未填写"}`,
        task?.due_at ? `截止时间：${readableTime(task.due_at)}` : "截止时间：未设置",
        task?.result_text ? `完成结果：${task.result_text}` : "",
        task?.completion_evidence?.length ? `完成证据：${task.completion_evidence.join("、")}` : "",
        historyLines.length ? `状态历史：\n\n${historyLines.join("\n\n")}` : "状态历史正在读取。",
        "边界：任务用于保存事实核验和研究复核，不代表买卖、仓位或收益判断。"
      ].filter(Boolean).join("\n\n");
    }

    async function openObservationTaskHistory(task) {
      try {
        const detail = await api(`/v1/observation-tasks/${encodeURIComponent(task.id)}`);
        openReader(detail.title || "观察任务", observationTaskHistoryDetail(detail), `${detail.status_label || "研究任务"} · 版本 ${detail.version}`);
      } catch (error) {
        openReader(task.title || "观察任务", error.message || "任务历史暂时无法读取。", "请稍后重试");
      }
    }

    async function refreshObservationTaskView(symbol) {
      state.stockSpaceTab = "tasks";
      await loadDeepStockOverview(symbol);
      activateStockSpaceTab("tasks");
    }

    async function transitionObservationTask(symbol, task, status, resultText = null, evidenceRefs = []) {
      await api(`/v1/observation-tasks/${encodeURIComponent(task.id)}/transition`, {
        method: "POST",
        body: JSON.stringify({base_version: task.version, status, result_text: resultText, evidence_refs: evidenceRefs})
      });
      await refreshObservationTaskView(symbol);
    }

    function showObservationTaskCompletion(card, symbol, task) {
      if (card.querySelector(".stock-task-editor")) return;
      const editor = document.createElement("div"); editor.className = "stock-task-editor";
      const textarea = document.createElement("textarea"); textarea.setAttribute("aria-label", `${task.title}完成结果`); textarea.placeholder = "写下核验结果、仍未解决的疑点或引用的证据";
      const status = document.createElement("div"); status.className = "stock-task-editor-status"; status.textContent = "完成任务必须留下结果；结果会与状态历史一起长期保存。";
      const actions = document.createElement("div"); actions.className = "stock-task-actions";
      const save = document.createElement("button"); save.type = "button"; save.className = "btn primary"; save.textContent = "确认完成";
      const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "btn"; cancel.textContent = "取消";
      cancel.addEventListener("click", () => editor.remove());
      save.addEventListener("click", async () => {
        const result = textarea.value.trim();
        if (!result) { status.textContent = "请先填写本次核验结果。"; textarea.focus(); return; }
        save.disabled = true; cancel.disabled = true; status.textContent = "正在保存任务结果…";
        try { await transitionObservationTask(symbol, task, "completed", result); }
        catch (error) { save.disabled = false; cancel.disabled = false; status.textContent = error.message || "任务结果未保存，请重试。"; }
      });
      actions.append(save, cancel); editor.append(textarea, status, actions); card.appendChild(editor); textarea.focus();
    }

    function showObservationTaskEditor(card, symbol, task) {
      if (card.querySelector(".stock-task-editor")) return;
      const editor = document.createElement("div"); editor.className = "stock-task-editor";
      const title = document.createElement("input"); title.type = "text"; title.value = task.title || ""; title.setAttribute("aria-label", "任务标题");
      const description = document.createElement("textarea"); description.value = task.description || ""; description.setAttribute("aria-label", "任务说明");
      const priority = document.createElement("select"); priority.setAttribute("aria-label", "任务优先级");
      [["high", "高优先级"], ["normal", "普通优先级"], ["low", "低优先级"]].forEach(([value, label]) => { const option = document.createElement("option"); option.value = value; option.textContent = label; priority.appendChild(option); });
      priority.value = task.priority || "normal";
      const status = document.createElement("div"); status.className = "stock-task-editor-status"; status.textContent = "编辑会生成新版本，不会覆盖历史记录。";
      const actions = document.createElement("div"); actions.className = "stock-task-actions";
      const save = document.createElement("button"); save.type = "button"; save.className = "btn primary"; save.textContent = "保存修改";
      const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "btn"; cancel.textContent = "取消";
      cancel.addEventListener("click", () => editor.remove());
      save.addEventListener("click", async () => {
        if (!title.value.trim() || !description.value.trim()) { status.textContent = "任务标题和说明不能为空。"; return; }
        save.disabled = true; cancel.disabled = true; status.textContent = "正在保存新版本…";
        try {
          await api(`/v1/observation-tasks/${encodeURIComponent(task.id)}`, {method: "PATCH", body: JSON.stringify({base_version: task.version, title: title.value.trim(), description: description.value.trim(), priority: priority.value})});
          await refreshObservationTaskView(symbol);
        } catch (error) { save.disabled = false; cancel.disabled = false; status.textContent = error.message || "任务修改未保存，请重试。"; }
      });
      actions.append(save, cancel); editor.append(title, description, priority, status, actions); card.appendChild(editor); title.focus();
    }

    async function saveObservationTaskFromAction(symbol, action, button) {
      const original = button.textContent; button.disabled = true; button.textContent = "正在保存…";
      try {
        await api(`/v1/stocks/${encodeURIComponent(symbol)}/observation-tasks`, {
          method: "POST",
          body: JSON.stringify({
            title: action.title || "继续核验研究证据",
            description: action.next_step || action.current_evidence || "继续核验相关事实与反方证据。",
            priority: action.severity === "high" ? "high" : action.severity === "low" ? "low" : "normal",
            source_type: "research_action",
            source_ref_id: String(action.id || `${action.title}:${action.next_step}`).slice(0, 160)
          })
        });
        button.textContent = "已保存为任务";
        await refreshObservationTaskView(symbol);
      } catch (error) { button.disabled = false; button.textContent = original; openReader("任务暂未保存", error.message || "请稍后重试。", "系统建议仍保留在当前页面"); }
    }
