function readableTime(value) {
      if (!value) return "时间待确认";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return "时间待确认";
      return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    }

    function readableResearchPreview(value) {
      return String(value || "")
        .replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/g, match => readableTime(match))
        .replace(/。\s*(?=(?:最近完整日线|当前报价|下一步|复核))/g, "。\n")
        .replace(/[ \t]{2,}/g, " ")
        .trim();
    }

    function marketSessionDate(value, timezoneName = "UTC") {
      if (!value) return null;
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return null;
      try {
        return new Intl.DateTimeFormat("en-CA", {timeZone: timezoneName, year: "numeric", month: "2-digit", day: "2-digit"}).format(date);
      } catch { return date.toISOString().slice(0, 10); }
    }

    function cleanReaderInline(value) {
      return String(value || "").replace(/\*\*(.*?)\*\*/g, "$1").replace(/`([^`]+)`/g, "$1").trim();
    }

    function appendReaderText(container, body, documentTitle = "") {
      const lines = String(body || "内容正在生成。").split(/\r?\n/);
      let list = null;
      const flushList = () => {
        if (!list) return;
        container.appendChild(list);
        list = null;
      };
      for (const rawLine of lines) {
        const line = rawLine.trim();
        if (!line) { flushList(); continue; }
        const heading = line.match(/^(#{1,3})\s+(.+)$/);
        if (heading) {
          flushList();
          const headingText = cleanReaderInline(heading[2]);
          if (headingText === cleanReaderInline(documentTitle)) continue;
          const node = document.createElement("div");
          node.className = `reader-section-title${heading[1].length > 1 ? " sub" : ""}`;
          node.textContent = headingText;
          container.appendChild(node);
          continue;
        }
        const bullet = line.match(/^(?:[-*•]|\d+[.)])\s+(.+)$/);
        if (bullet) {
          if (!list) { list = document.createElement("ul"); list.className = "reader-list"; }
          const item = document.createElement("li"); item.textContent = cleanReaderInline(bullet[1]); list.appendChild(item);
          continue;
        }
        flushList();
        const node = document.createElement("p"); node.className = "reader-paragraph"; node.textContent = cleanReaderInline(line); container.appendChild(node);
      }
      flushList();
      if (!container.children.length) {
        const node = document.createElement("p"); node.className = "reader-paragraph"; node.textContent = "内容正在生成。"; container.appendChild(node);
      }
    }

    function renderReaderEventFeedback(event = null) {
      const container = $("readerEventFeedback");
      const relevant = $("readerEventRelevant");
      const irrelevant = $("readerEventIrrelevant");
      if (!event?.link_id) {
        container.hidden = true;
        relevant.classList.remove("active");
        irrelevant.classList.remove("active");
        return;
      }
      container.hidden = false;
      const status = event.relevance_status || "pending";
      relevant.classList.toggle("active", status === "relevant");
      irrelevant.classList.toggle("active", status === "irrelevant");
      relevant.setAttribute("aria-pressed", status === "relevant" ? "true" : "false");
      irrelevant.setAttribute("aria-pressed", status === "irrelevant" ? "true" : "false");
      $("readerEventFeedbackStatus").textContent = ({
        relevant: "已标记为与你有关，事件会保留在个人变化历史中。",
        irrelevant: "已标记为与你无关，不再进入待处理提醒。",
        pending: "你的判断只影响个人提醒，不会修改公共事实。"
      })[status] || "你的判断只影响个人提醒，不会修改公共事实。";
    }

    function changeEventReaderBody(event) {
      const payload = event?.payload || {};
      const details = [
        event?.fact_summary || "这条变化已经进入个人研究空间。",
        `事件类型：${event?.event_type_label || "已验收变化"}`,
        `事实时间：${readableTime(event?.occurred_at)}`,
        `来源：${event?.source_name || "已归档来源"}`,
        `数据状态：${event?.data_status_label || "事实已归档"}`
      ];
      if (event?.event_type === "daily_price_anomaly" && payload.current_quote_excluded) {
        details.push("时间口径：异常判断只使用上一根完整日线；当天盘中报价没有被当成收盘数据。 ");
      }
      details.push(`研究边界：${event?.boundary || "事件事实不等于股价因果或交易信号。"}`);
      return details.filter(Boolean).join("\n\n");
    }

    async function openChangeEvent(linkId) {
      if (!linkId) return;
      try {
        let event = await api(`/v1/changes/${encodeURIComponent(linkId)}`);
        try {
          event = await api(`/v1/user-changes/${encodeURIComponent(linkId)}/read`, {method: "POST"});
        } catch { /* Reading the fact remains available if the state update is delayed. */ }
        openReader(
          event.title || "重要变化",
          changeEventReaderBody(event),
          [event.name || event.symbol, event.relevance_status_label, readableTime(event.occurred_at)].filter(Boolean).join(" · "),
          event.source_url || "",
          {changeEvent: event}
        );
        void loadTodayOverview();
      } catch (error) {
        openReader("变化详情暂未打开", error?.message || "请稍后重试。", "当前页面中的研究资料仍然保留");
      }
    }

    async function setReaderChangeRelevance(relevanceStatus) {
      const event = state.readerContext?.changeEvent;
      if (!event?.link_id) return;
      const relevant = $("readerEventRelevant");
      const irrelevant = $("readerEventIrrelevant");
      relevant.disabled = true;
      irrelevant.disabled = true;
      try {
        const updated = await api(`/v1/user-changes/${encodeURIComponent(event.link_id)}/relevance`, {
          method: "POST",
          body: JSON.stringify({relevance_status: relevanceStatus})
        });
        state.readerContext.changeEvent = updated;
        renderReaderEventFeedback(updated);
        void loadTodayOverview();
        if (state.workspacePage === "deep_stock" && state.deepStockOverviewSymbol === updated.symbol) {
          void loadDeepStockOverview(updated.symbol);
        }
      } catch (error) {
        $("readerEventFeedbackStatus").textContent = error?.message || "相关性暂未保存，请稍后重试。";
      } finally {
        relevant.disabled = false;
        irrelevant.disabled = false;
      }
    }

    function openReader(title, body, meta = "", sourceUrl = "") {
      const options = arguments[4] || {};
      state.readerContext = {
        title: title || "研究内容",
        meta,
        body: body || "",
        changeEvent: options.changeEvent || null,
        agentQuestion: options.agentQuestion || null
      };
      state.readerReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      $("readerTitle").textContent = title || "研究内容";
      $("readerMeta").textContent = meta;
      const readerBody = $("readerBody");
      readerBody.innerHTML = "";
      const copy = document.createElement("div"); copy.className = "reader-body-copy";
      appendReaderText(copy, body, title);
      readerBody.appendChild(copy);
      if (sourceUrl) {
        try {
          const parsed = new URL(sourceUrl, window.location.href);
          if (["http:", "https:"].includes(parsed.protocol)) {
            const link = document.createElement("a"); link.className = "reader-source-link"; link.href = parsed.href; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = "打开原始公告或信息源 ↗";
            readerBody.appendChild(link);
          }
        } catch { /* Invalid source links remain hidden. */ }
      }
      renderReaderEventFeedback(options.changeEvent || null);
      $("readerBackdrop").classList.add("open");
      $("readerBackdrop").setAttribute("aria-hidden", "false");
      document.body.style.overflow = "hidden";
      requestAnimationFrame(() => $("readerClose").focus());
    }

    function closeReader() {
      $("readerBackdrop").classList.remove("open");
      $("readerBackdrop").setAttribute("aria-hidden", "true");
      document.body.style.overflow = "";
      if (state.readerReturnFocus?.isConnected) state.readerReturnFocus.focus();
      state.readerReturnFocus = null;
    }
