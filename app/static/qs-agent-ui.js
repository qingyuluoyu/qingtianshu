function tone(value) {
      if (value > 0) return "up";
      if (value < 0) return "down";
      return "flat";
    }
    function watchlistQuote(item) {
      const current = item.current_quote || item.quote || {};
      const change = current.pct_change ?? item.metrics?.return_1d_pct;
      return {
        price: current.price ?? item.latest_bar?.close ?? item.metrics?.latest_close,
        change,
        label: current.label || "最近收盘",
        marketTimestamp: current.market_timestamp || item.market_timestamp,
        status: current.status || item.status
      };
    }
    function appendInlineMarkdown(target, text) {
      const pattern = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;
      let cursor = 0;
      for (const match of text.matchAll(pattern)) {
        if (match.index > cursor) target.appendChild(document.createTextNode(text.slice(cursor, match.index)));
        if (match[0].startsWith("**")) {
          const strong = document.createElement("strong");
          strong.textContent = match[0].slice(2, -2);
          target.appendChild(strong);
        } else {
          const code = document.createElement("code");
          code.textContent = match[0].slice(1, -1);
          target.appendChild(code);
        }
        cursor = match.index + match[0].length;
      }
      if (cursor < text.length) target.appendChild(document.createTextNode(text.slice(cursor)));
    }
    function renderMarkdown(text) {
      const fragment = document.createDocumentFragment();
      const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
      let list = null;
      let listType = null;
      let codeLines = null;
      let firstContent = true;
      const plainSectionHeading = /^(?:直接结论|核心判断|当日价格事实|最新行情事实|价格事实|财务与财报证据|财务与公告证据(?:（反方为主）)?|已确认的财务与公告证据|支持事件与反方事件|当日媒体叙事|可能解释|反方证据|不能确认的部分|证据边界|风险边界|结论)$/;
      const keyBoundaryLead = /^(最关键的不能确认部分|最关键的证据边界|最关键的反方证据|结论)[：:]\s*(.+)$/;
      const closeList = () => { list = null; listType = null; };
      const appendCode = () => {
        if (!codeLines) return;
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        code.textContent = codeLines.join("\n");
        pre.appendChild(code); fragment.appendChild(pre); codeLines = null;
      };
      for (const line of lines) {
        if (/^```/.test(line.trim())) {
          if (codeLines) appendCode();
          else { closeList(); codeLines = []; }
          continue;
        }
        if (codeLines) { codeLines.push(line); continue; }
        if (!line.trim()) { closeList(); continue; }
        const heading = line.match(/^(#{1,4})\s+(.+)$/);
        if (heading) {
          closeList();
          const level = Math.min(4, heading[1].length + 1);
          const node = document.createElement(`h${level}`);
          appendInlineMarkdown(node, heading[2]); fragment.appendChild(node); firstContent = false; continue;
        }
        const chineseHeading = line.match(/^([一二三四五六七八九十]+[、.．])\s*(.+)$/);
        if (chineseHeading) {
          closeList();
          const node = document.createElement("h3");
          appendInlineMarkdown(node, `${chineseHeading[1]}${chineseHeading[2]}`); fragment.appendChild(node); firstContent = false; continue;
        }
        const trimmed = line.trim();
        if (plainSectionHeading.test(trimmed)) {
          closeList();
          const node = document.createElement("h3");
          node.textContent = trimmed; fragment.appendChild(node); firstContent = false; continue;
        }
        const unordered = line.match(/^\s*[-*]\s+(.+)$/);
        const ordered = line.match(/^\s*\d+[.)、]\s+(.+)$/);
        if (unordered || ordered) {
          const nextType = ordered ? "ol" : "ul";
          if (!list || listType !== nextType) {
            list = document.createElement(nextType); listType = nextType; fragment.appendChild(list);
          }
          const item = document.createElement("li");
          appendInlineMarkdown(item, (ordered || unordered)[1]); list.appendChild(item); firstContent = false; continue;
        }
        closeList();
        const quote = line.match(/^>\s?(.+)$/);
        const node = document.createElement(quote ? "blockquote" : "p");
        const copy = quote ? quote[1] : line;
        const boundary = !quote ? copy.match(keyBoundaryLead) : null;
        if (boundary) {
          node.className = "answer-key-boundary";
          const strong = document.createElement("strong"); strong.textContent = `${boundary[1]}：`;
          node.append(strong, document.createTextNode(boundary[2]));
        } else {
          if (firstContent && copy.length <= 80 && /(?:不能确认|可以确认|尚不能|结论|不支持|支持)/.test(copy)) node.className = "answer-conclusion";
          appendInlineMarkdown(node, copy);
        }
        fragment.appendChild(node);
        firstContent = false;
      }
      appendCode();
      return fragment;
    }
    function appendMessageSources(node, metadata) {
      const answerSources = collectAnswerSources(metadata);
      const sourceCount = answerSources.length;
      if (!sourceCount) return;
      const sources = document.createElement("details");
      sources.className = "message-sources";
      const summary = document.createElement("summary"); summary.textContent = `查看本轮证据与引用 · ${sourceCount} 项`;
      const list = document.createElement("div"); list.className = "message-source-list";
      answerSources.forEach(source => {
        const row = document.createElement(source.url ? "a" : source.documentId || source.copy ? "button" : "div");
        if (row.tagName === "BUTTON") row.type = "button";
        if (source.url) { row.href = source.url; row.target = "_blank"; row.rel = "noopener noreferrer"; }
        row.className = "message-source-item";
        const kind = document.createElement("span"); kind.className = "message-source-kind"; kind.textContent = source.tag || "证据";
        const title = document.createElement("span"); title.className = "message-source-title"; title.textContent = source.title || "研究资料";
        row.append(kind, title);
        if (source.copy) {
          const copy = document.createElement("span"); copy.className = "message-source-copy"; copy.textContent = source.copy; row.appendChild(copy);
        }
        if (source.meta) {
          const meta = document.createElement("span"); meta.className = "message-source-meta"; meta.textContent = source.meta; row.appendChild(meta);
        }
        if (source.documentId) row.addEventListener("click", async () => {
          row.disabled = true;
          try {
            const document = await api(`/me/knowledge/${encodeURIComponent(source.documentId)}`);
            openReader(document.title || source.title, document.content || "这份资料暂时没有可阅读正文。", `${source.scope === "user" ? "个人资料" : "通用资料"} · 更新 ${readableTime(document.updated_at)}`);
          } catch (error) {
            openReader(source.title || "研究资料", error?.message || "这份资料暂时无法读取。", "资料读取未完成");
          } finally { row.disabled = false; }
        });
        else if (!source.url && source.copy && row.tagName === "BUTTON") row.addEventListener("click", () => {
          openReader(source.title || "本轮证据", source.copy, source.meta || source.tag || "结构化证据");
        });
        list.appendChild(row);
      });
      sources.append(summary, list);
      node.appendChild(sources);
    }
    function aiWritebackPresentation(candidate) {
      const payload = candidate.payload || {};
      if (candidate.candidate_type === "observation_task") return {
        title: "AI 整理的观察任务 · 需要你确认",
        copy: [`任务：${payload.title || "本轮证据核验"}`, `核验内容：${payload.description || ""}`].join("\n\n"),
        confirm: "确认创建观察任务",
        pending: "确认前不会创建个人任务。",
        working: "正在创建观察任务…",
        confirmed: "已由你确认，并保存为个人观察任务。",
        rejected: "已放弃，本次没有创建观察任务。",
        stale: "股票研究空间已变化，这份任务候选已失效。"
      };
      if (candidate.candidate_type === "action_plan") return {
        title: "AI 整理的操作计划草稿 · 需要你确认",
        copy: [`计划方向：${actionPlanTypeLabel(payload.action_type)}`, `复核条件：${payload.trigger_text || ""}`, payload.boundary || ""].filter(Boolean).join("\n\n"),
        confirm: "确认保存计划草稿",
        pending: "确认前不会创建计划；AI 不填写目标价、仓位或收益承诺。",
        working: "正在保存计划草稿…",
        confirmed: "已由你确认，并保存为可继续检查的操作计划草稿。",
        rejected: "已放弃，本次没有创建操作计划。",
        stale: "正式判断或股票空间已变化，这份计划候选已失效。"
      };
      if (candidate.candidate_type === "review_draft") return {
        title: "AI 生成的交易复盘草稿 · 需要你确认",
        copy: [`确定性价格结果：${payload.price_result || ""}`, `逻辑复盘：${payload.logic_result || ""}`, payload.plan_deviation ? `计划偏离：${payload.plan_deviation}` : "", payload.improvement_text ? `下一次改进：${payload.improvement_text}` : ""].filter(Boolean).join("\n\n"),
        confirm: "确认写入可编辑草稿",
        pending: "确认前不会改变复盘；写入后仍需你编辑并最终确认。",
        working: "正在写入可编辑复盘草稿…",
        confirmed: "已写入可编辑草稿；最终复盘仍需你确认。",
        rejected: "已放弃，原复盘没有变化。",
        stale: "复盘状态或版本已变化，这份草稿已失效。"
      };
      return {
        title: "AI 提出的判断草稿 · 需要你确认",
        copy: [payload.current_reason_text ? `当前判断：${payload.current_reason_text}` : "当前尚无正式判断", `建议草稿：${payload.reason_text || ""}`].join("\n\n"),
        confirm: "确认写入当前判断",
        pending: "确认前不会修改正式判断。",
        working: "正在写入版本化判断…",
        confirmed: "已由你确认，并写入版本化当前判断。",
        rejected: "已拒绝，正式判断没有变化。",
        stale: "正式判断已更新，这份草稿已失效。"
      };
    }
    function appendAIWritebackCandidate(host, candidate, options = {}) {
      const presentation = aiWritebackPresentation(candidate);
      const card = document.createElement("div"); card.className = "ai-writeback-card";
      const title = document.createElement("div"); title.className = "ai-writeback-title"; title.textContent = presentation.title;
      const copy = document.createElement("div"); copy.className = "ai-writeback-copy"; copy.textContent = presentation.copy;
      const actions = document.createElement("div"); actions.className = "ai-writeback-actions";
      const confirm = document.createElement("button"); confirm.type = "button"; confirm.className = "btn primary"; confirm.textContent = presentation.confirm;
      const reject = document.createElement("button"); reject.type = "button"; reject.className = "btn ghost"; reject.textContent = "暂不采用";
      const status = document.createElement("div"); status.className = "ai-writeback-status";
      const applyStatus = value => {
        candidate.status = value;
        const pending = value === "pending_confirmation";
        confirm.hidden = !pending; reject.hidden = !pending;
        status.textContent = presentation[value] || presentation.pending;
      };
      confirm.addEventListener("click", async () => {
        confirm.disabled = true; reject.disabled = true; status.textContent = presentation.working;
        try {
          const result = await api(`/v1/ai-writebacks/${encodeURIComponent(candidate.id)}/confirm`, {method: "POST"});
          applyStatus(result.status || "confirmed");
          await loadWatchlist();
          if (candidate.symbol && $("deepStockSymbol")?.value === candidate.symbol) await loadDeepStockOverview(candidate.symbol);
          if (options.onConfirmed) await options.onConfirmed(result);
        } catch (error) {
          status.textContent = error.message || "暂时无法确认这份 AI 草稿。";
          confirm.disabled = false; reject.disabled = false;
        }
      });
      reject.addEventListener("click", async () => {
        confirm.disabled = true; reject.disabled = true; status.textContent = "正在保留现有数据…";
        try {
          const result = await api(`/v1/ai-writebacks/${encodeURIComponent(candidate.id)}/reject`, {method: "POST"});
          applyStatus(result.status || "rejected");
          if (options.onRejected) await options.onRejected(result);
        } catch (error) {
          status.textContent = error.message || "暂时无法处理这份 AI 草稿。";
          confirm.disabled = false; reject.disabled = false;
        }
      });
      actions.append(confirm, reject); card.append(title, copy, actions, status); host.appendChild(card); applyStatus(candidate.status);
      void api(`/v1/ai-writebacks/${encodeURIComponent(candidate.id)}`).then(current => applyStatus(current.status)).catch(() => {});
      return card;
    }
    function appendStructuredAnswer(node, metadata) {
      const structured = metadata?.structured_answer || metadata?.structuredAnswer;
      if (!structured || structured.contract_version !== "structured_ai_response_v1") return;
      const citations = new Map((structured.citations || []).map(item => [String(item.id), item]));
      const facts = structured.confirmed_facts || [];
      const inferences = structured.evidence_based_inferences || [];
      const risks = structured.counter_evidence_and_risks || [];
      const hypotheses = structured.hypotheses_to_verify || [];
      const gaps = structured.information_gaps || [];
      const invalidations = structured.invalidation_conditions || [];
      const nextTasks = structured.next_evidence_tasks || [];
      const details = document.createElement("details"); details.className = "structured-answer";
      const summary = document.createElement("summary");
      summary.textContent = `结构化证据 · 事实 ${facts.length} · 反证 ${risks.length} · 待核验 ${hypotheses.length + gaps.length}`;
      const body = document.createElement("div"); body.className = "structured-answer-body";
      const appendSection = (label, items, fallbackText = "") => {
        if (!(items || []).length && !fallbackText) return;
        const section = document.createElement("div"); section.className = "structured-answer-section";
        const title = document.createElement("div"); title.className = "structured-answer-label"; title.textContent = label;
        section.appendChild(title);
        for (const item of (items || []).slice(0, 4)) {
          const text = String(item.text || item.evidence_summary || item.description || item.condition || "").trim();
          if (!text) continue;
          const citation = citations.get(String((item.citation_ids || [])[0] || ""));
          const row = document.createElement(citation ? "button" : "div"); row.className = "structured-answer-item";
          if (citation) row.type = "button";
          row.textContent = text;
          if (citation) row.addEventListener("click", () => {
            const time = citation.data_time || citation.report_period || "时间待核验";
            const limitations = (citation.limitations || []).join("\n");
            openReader(
              citation.source_name || "结构化证据",
              [citation.excerpt, limitations ? `口径限制：${limitations}` : ""].filter(Boolean).join("\n\n"),
              `${citation.evidence_type || "证据"} · ${time}`
            );
          });
          section.appendChild(row);
        }
        if (!(items || []).length && fallbackText) {
          const row = document.createElement("div"); row.className = "structured-answer-item"; row.textContent = fallbackText; section.appendChild(row);
        }
        body.appendChild(section);
      };
      appendSection("已确认事实", facts);
      appendSection("证据支持的推断", inferences);
      appendSection("反方证据与风险", risks);
      appendSection("待验证假设", hypotheses);
      appendSection("信息缺口", gaps);
      appendSection("什么时候需要重新判断", invalidations);
      appendSection("下一步核验", nextTasks);
      appendSection("结论边界", [], structured.conclusion_boundary || "");
      details.append(summary, body); node.appendChild(details);
      for (const candidate of (structured.candidate_writebacks || [])) {
        appendAIWritebackCandidate(node, candidate);
      }
    }
    function appendMessageActions(node, text) {
      const actions = document.createElement("div"); actions.className = "message-actions";
      const copy = document.createElement("button");
      copy.type = "button"; copy.className = "message-action"; copy.textContent = "复制"; copy.title = "复制回答";
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(text);
          copy.textContent = "已复制";
          setTimeout(() => { copy.textContent = "复制"; }, 1200);
        } catch { copy.textContent = "复制失败"; }
      });
      actions.appendChild(copy); node.appendChild(actions);
    }
    function appendAgentRunBoundary(node, {kind = "degraded", title, copy, question}) {
      if (!node) return;
      node.querySelectorAll(":scope > .agent-run-boundary").forEach(item => item.remove());
      const boundary = document.createElement("section");
      boundary.className = `agent-run-boundary ${kind}`;
      const heading = document.createElement("div");
      heading.className = "agent-run-boundary-title";
      heading.textContent = title;
      const detail = document.createElement("div");
      detail.className = "agent-run-boundary-copy";
      detail.textContent = copy;
      const actions = document.createElement("div");
      actions.className = "agent-run-boundary-actions";
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "btn primary";
      retry.textContent = "重新用 Hermes 研究";
      retry.addEventListener("click", async () => {
        retry.disabled = true;
        retry.textContent = "正在重新连接…";
        await loadHealth().catch(() => null);
        if (kind === "failed") node.remove();
        else boundary.remove();
        await sendChat(question, {reuseUserMessage: true});
      });
      actions.appendChild(retry);
      boundary.append(heading, detail, actions);
      node.appendChild(boundary);
    }
    function renderAgentFailure(node, question, error, directHermes) {
      const title = directHermes ? "本轮即时研究没有完成" : "Hermes 当前未连接";
      const copy = directHermes
        ? "没有形成通过校验的 AI 结论。当前问题和已保存会话仍然保留，系统不会用预存文案或未经标注的确定性摘要冒充即时回答。"
        : "当前只具备确定性数据工具，尚不能即时生成 AI 回答。系统没有发送或保存一段基础摘要来冒充 Hermes；恢复连接后可直接重试原问题。";
      const statusHint = Number(error?.status || 0);
      const visibleCopy = statusHint === 429
        ? `${copy} 当前服务请求较多，请稍后重试。`
        : copy;
      const response = finalizeStreamingMessage(
        node,
        directHermes
          ? "本轮没有生成可用的即时研究回答。"
          : "Hermes 未连接，本轮没有生成 AI 回答。",
        null
      );
      appendAgentRunBoundary(response, {
        kind: "failed",
        title,
        copy: visibleCopy,
        question
      });
    }
    function renderMessageContent(node, role, text, pending, metadata) {
      node.textContent = "";
      if (role === "agent" && !pending) {
        renderFinalAnswerBody(node, text);
        appendStructuredAnswer(node, metadata);
        appendMessageSources(node, metadata);
        appendMessageActions(node, text);
      } else {
        node.textContent = text;
      }
    }
    function addMessage(role, text, pending = false, metadata = null) {
      const node = document.createElement("div");
      node.className = `message ${role}${pending ? " pending" : ""}`;
      if (role === "agent" && pending) node.dataset.userNavigatedDuringRun = "false";
      renderMessageContent(node, role, text, pending, metadata);
      $("messages").appendChild(node);
      $("messages").scrollTop = $("messages").scrollHeight;
      return node;
    }
    function replaceMessageContent(node, text, metadata = null) {
      if (!node) return;
      node.classList.remove("pending");
      node.classList.remove("streaming-progress");
      node.agentEvidenceProgress = null;
      renderMessageContent(node, "agent", text, false, metadata);
    }
    function appendFinalMessageMetadata(node, text, metadata = null) {
      if (!node || !metadata) return;
      node.querySelectorAll(":scope > .structured-answer, :scope > .message-sources, :scope > .ai-writeback-card, :scope > .message-actions")
        .forEach(child => child.remove());
      appendStructuredAnswer(node, metadata);
      appendMessageSources(node, metadata);
      appendMessageActions(node, text);
    }
    function userNavigatedDuringAgentRun(node) {
      return node?.dataset.userNavigatedDuringRun === "true";
    }
    function scrollAgentMessage(node, {anchorStart = false} = {}) {
      if (!node?.isConnected || userNavigatedDuringAgentRun(node)) return;
      const messages = $("messages");
      const relativeTop = node.getBoundingClientRect().top
        - messages.getBoundingClientRect().top + messages.scrollTop;
      messages.scrollTop = anchorStart
        ? Math.max(0, relativeTop - 12)
        : messages.scrollHeight;
      if (anchorStart) {
        const visibleTop = 92;
        const messagesTop = messages.getBoundingClientRect().top;
        if (messagesTop < visibleTop || messagesTop > window.innerHeight * .35) {
          window.scrollTo({
            top: Math.max(0, window.scrollY + messagesTop - visibleTop),
            behavior: "smooth"
          });
        }
      }
    }
    function finalizeStreamingMessage(node, text, metadata = null, options = {}) {
      if (!node) return null;
      const finalText = String(text || "");
      const finalAlreadyVisible = node.dataset.finalAnswerVisible === "true";
      const sameFinalAnswer = node.dataset.finalAnswer === finalText;
      if (finalAlreadyVisible && !options.replaceFinal) {
        if (sameFinalAnswer) appendFinalMessageMetadata(node, finalText, metadata);
        return node;
      }
      replaceMessageContent(node, finalText, metadata);
      node.classList.add("stream-finalized");
      node.dataset.finalAnswerVisible = "true";
      node.dataset.finalAnswer = finalText;
      const messages = $("messages");
      const longAnswer = node.offsetHeight > messages.clientHeight * .68 || finalText.length > 520;
      scrollAgentMessage(node, {anchorStart: longAnswer});
      return node;
    }
    function verifiedAnswerBlocks(text) {
      const blocks = String(text || "").trim().split(/\n{2,}/).map(item => item.trim()).filter(Boolean);
      return blocks.length ? blocks : [String(text || "")];
    }
    function compactAnswerTextForComparison(text) {
      return String(text || "").replace(/\s+/g, "");
    }
    async function renderVerifiedAnswerProgressively(node, text) {
      if (!node || node.dataset.finalAnswerVisible === "true") return node;
      const finalText = String(text || "");
      if (node.dataset.guardedPartialVisible === "true") {
        const finalSections = splitAnswerFootnotes(finalText);
        const finalMain = String(finalSections.main || "").trim();
        const partialText = String(node.dataset.guardedPartialText || "").trim();
        const body = node.querySelector(":scope > .message-body");
        if (body && partialText && finalMain.startsWith(partialText)) {
          const suffix = finalMain.slice(partialText.length).trim();
          if (suffix) body.appendChild(renderMarkdown(suffix));
          node.querySelector(":scope > .guarded-stream-label")?.remove();
          appendAnswerFootnotes(node, finalSections.footnotes);
          node.classList.remove("pending", "streaming-progress", "guarded-streaming-answer");
          node.classList.add("stream-finalized");
          node.dataset.finalAnswerVisible = "true";
          node.dataset.finalAnswer = finalText;
          scrollAgentMessage(node, {anchorStart: finalText.length > 520});
          return node;
        }
        if (
          body
          && partialText
          && compactAnswerTextForComparison(finalMain) === compactAnswerTextForComparison(partialText)
        ) {
          node.querySelector(":scope > .guarded-stream-label")?.remove();
          appendAnswerFootnotes(node, finalSections.footnotes);
          node.classList.remove("pending", "streaming-progress", "guarded-streaming-answer");
          node.classList.add("stream-finalized");
          node.dataset.finalAnswerVisible = "true";
          node.dataset.finalAnswer = finalText;
          scrollAgentMessage(node, {anchorStart: finalText.length > 520});
          return node;
        }
        return finalizeStreamingMessage(node, finalText);
      }
      const sections = splitAnswerFootnotes(finalText);
      const blocks = verifiedAnswerBlocks(sections.main);
      if (blocks.length < 2 || window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) {
        return finalizeStreamingMessage(node, finalText);
      }
      node.classList.remove("pending", "streaming-progress");
      node.agentEvidenceProgress = null;
      node.textContent = "";
      const body = document.createElement("div"); body.className = "message-body"; node.appendChild(body);
      node.classList.add("stream-finalized", "verified-progressive-answer");
      node.dataset.finalAnswerVisible = "true";
      node.dataset.finalAnswer = finalText;
      const longAnswer = finalText.length > 520 || blocks.length > 4;
      const delay = Math.max(28, Math.min(65, Math.round(260 / blocks.length)));
      for (let index = 0; index < blocks.length; index += 1) {
        body.appendChild(renderMarkdown(blocks[index]));
        scrollAgentMessage(node, {anchorStart: longAnswer});
        if (index < blocks.length - 1) await new Promise(resolve => setTimeout(resolve, delay));
      }
      appendAnswerFootnotes(node, sections.footnotes);
      node.classList.remove("verified-progressive-answer");
      return node;
    }
    function renderGuardedPartialAnswer(node, text) {
      if (!node?.isConnected || node.dataset.finalAnswerVisible === "true") return;
      const draft = String(text || "").trim();
      const sections = splitAnswerFootnotes(draft);
      const mainText = String(sections.main || "").trim();
      if (!mainText || mainText === node.dataset.guardedPartialText) return;
      const previousText = String(node.dataset.guardedPartialText || "").trim();
      const existingBody = node.querySelector(":scope > .message-body");
      if (
        node.dataset.guardedPartialVisible === "true"
        && existingBody
        && previousText
        && mainText.startsWith(previousText)
      ) {
        const suffix = mainText.slice(previousText.length).trim();
        if (suffix) existingBody.appendChild(renderMarkdown(suffix));
        node.dataset.guardedPartialText = mainText;
        scrollAgentMessage(node, {anchorStart: true});
        return;
      }
      node.classList.remove("pending");
      node.classList.add("streaming-progress", "guarded-streaming-answer");
      node.agentEvidenceProgress = null;
      node.textContent = "";
      const label = document.createElement("div");
      label.className = "guarded-stream-label";
      label.textContent = "正在生成 · 已显示目前可确认的内容";
      const body = document.createElement("div"); body.className = "message-body";
      body.appendChild(renderMarkdown(mainText));
      node.append(label, body);
      node.dataset.guardedPartialVisible = "true";
      node.dataset.guardedPartialText = mainText;
      scrollAgentMessage(node, {anchorStart: true});
    }
    function markActiveAgentScrollIntent() {
      for (const request of state.pendingAgentRequests.values()) {
        const node = request?.node || request;
        if (node?.isConnected && node.dataset.finalAnswerVisible !== "true") {
          node.dataset.userNavigatedDuringRun = "true";
        }
      }
    }
    $("messages").addEventListener("wheel", markActiveAgentScrollIntent, {passive: true});
    $("messages").addEventListener("touchstart", markActiveAgentScrollIntent, {passive: true});
    $("messages").addEventListener("pointerdown", markActiveAgentScrollIntent, {passive: true});
    document.addEventListener("keydown", event => {
      if (!["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(event.key)) return;
      if (event.target?.closest?.("input, textarea, select, [contenteditable='true']")) return;
      markActiveAgentScrollIntent();
    });
    function renderStreamingProgress(node, label = "AI 正在整理证据并生成回答…", evidenceProgress = null) {
      if (!node?.isConnected || node.dataset.finalAnswerVisible === "true") return;
      if (node.dataset.guardedPartialVisible === "true") return;
      node.classList.add("pending", "streaming-progress");
      const firstEvidenceSummary = Boolean(evidenceProgress?.items?.length) && !node.agentEvidenceProgress?.items?.length;
      if (evidenceProgress?.items?.length) node.agentEvidenceProgress = evidenceProgress;
      const progress = node.agentEvidenceProgress;
      node.textContent = "";
      const card = document.createElement("div"); card.className = "agent-progress-card";
      const status = document.createElement("div"); status.className = "agent-progress-status"; status.textContent = label;
      card.appendChild(status);
      if (progress?.items?.length) {
        const title = document.createElement("div"); title.className = "agent-progress-title"; title.textContent = progress.title || "本轮已读取的研究证据";
        const items = document.createElement("div"); items.className = "agent-progress-items";
        progress.items.forEach(item => {
          const row = document.createElement("div"); row.className = "agent-progress-item";
          const itemLabel = document.createElement("div"); itemLabel.className = "agent-progress-label"; itemLabel.textContent = item.label || "研究输入";
          const detail = document.createElement("div"); detail.className = "agent-progress-detail"; detail.textContent = item.detail || "已取得";
          row.append(itemLabel, detail); items.appendChild(row);
        });
        const boundary = document.createElement("div"); boundary.className = "agent-progress-boundary"; boundary.textContent = progress.boundary || "以上是本轮已取得的输入，不代表最终判断。";
        card.append(title, items, boundary);
      }
      node.appendChild(card);
      const messages = $("messages");
      scrollAgentMessage(node, {
        anchorStart: firstEvidenceSummary && card.offsetHeight > messages.clientHeight * .62
      });
    }
    function connectPrivateAgentStream(requestId, pending) {
      const source = new EventSource(`/me/chat/stream/${encodeURIComponent(requestId)}`);
      const context = {node: pending, source, finalText: "", finalShown: false, opened: false};
      state.pendingAgentRequests.set(requestId, context);
      let settleReady;
      const ready = new Promise(resolve => { settleReady = resolve; });
      const timer = setTimeout(() => settleReady(), 600);
      source.onopen = () => {
        context.opened = true;
        clearTimeout(timer);
        settleReady();
      };
      source.onmessage = event => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "agent_progress" && data.label && !context.finalShown) {
            renderStreamingProgress(pending, data.label, data.evidence_progress);
          }
          if (data.type === "agent_delta" && data.draft) {
            if (data.is_unverified === false && data.is_final === true) {
              context.finalText = data.draft;
              context.finalShown = true;
              context.finalRenderPromise = pending.dataset.finalAnswerVisible === "true"
                ? Promise.resolve(pending)
                : renderVerifiedAnswerProgressively(pending, context.finalText);
            } else if (data.is_guarded_partial === true) {
              renderGuardedPartialAnswer(pending, data.draft);
            } else {
              renderStreamingProgress(pending, "回答草稿已生成，正在核对行情、数字和证据…");
            }
          }
          if (data.type === "agent_stream_status" && data.label && !context.finalShown) {
            if (data.reset === true) {
              delete pending.dataset.guardedPartialVisible;
              delete pending.dataset.guardedPartialText;
              pending.classList.remove("guarded-streaming-answer");
            }
            renderStreamingProgress(pending, data.label);
          }
          if (["agent_stream_complete", "agent_stream_error"].includes(data.type)) source.close();
        } catch { /* malformed private events do not affect the final HTTP answer */ }
      };
      source.onerror = () => {
        clearTimeout(timer);
        settleReady();
      };
      return {source, ready, context};
    }
    function visibleConversationItems(items = []) {
      return items.filter(item => state.evaluationMode
        ? item.quality_scope === "evaluation"
        : item.quality_scope !== "evaluation")
        .filter(item => Number(item.message_count || 0) > 0 || item.id === state.conversationId);
    }
    function conversationDateSection(value) {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return {key: "unknown", label: "更早"};
      const today = new Date();
      const day = new Date(date.getFullYear(), date.getMonth(), date.getDate());
      const currentDay = new Date(today.getFullYear(), today.getMonth(), today.getDate());
      const dayOffset = Math.round((currentDay.getTime() - day.getTime()) / 86400000);
      if (dayOffset <= 0) return {key: "today", label: "今天"};
      if (dayOffset === 1) return {key: "yesterday", label: "昨天"};
      if (dayOffset < 7) return {key: "recent", label: "最近 7 天"};
      return {key: "older", label: "更早"};
    }
    function conversationTopicKey(item) {
      return String(item?.title || "新的研究对话")
        .replace(/\s+/g, " ")
        .replace(/[？?。！!]+$/g, "")
        .trim()
        .toLocaleLowerCase("zh-CN");
    }
    function conversationScopeKey(item) {
      const explicitScope = String(item?.conversation_scope || "").trim();
      if (["stock", "market", "screening", "portfolio", "funds", "other"].includes(explicitScope)) return explicitScope;
      const intent = String(item?.last_intent || "").trim();
      const title = String(item?.title || "");
      const preview = String(item?.last_message_preview || "");
      const text = `${title} ${preview}`;
      if (/自选股|关注与持仓|关注组合|持仓股票|我的关注|我的自选/.test(title)) return "portfolio";
      if (/基金|ETF|LOF|REIT|QDII|银行理财|理财产品|股票和基金|基金和股票|股票基金|债券|固收|存款|养老|退休|资产配置|风险承受|风险画像/i.test(text)) return "funds";
      if (/筛选|李总策略|候选股票|候选股|筛出|(^|[^自])选股/.test(title)) return "screening";
      if (/成交额|涨跌家数|普跌|结构性行情|大盘|主要指数|(A股|美股|港股|日股|韩股|欧股|伦敦金).{0,12}(收盘|市场|指数|涨跌|成交)/.test(title)) return "market";
      if (/个股研究|该股|这只股票|这家公司|相对.{0,10}(行业|板块)|(行业|板块).{0,6}(更强|更弱)|股票代码|[036]\d{5}/.test(title)) return "stock";
      if (intent === "stock_screen") return "screening";
      if (["market_brief", "market_pulse_article"].includes(intent)) return "market";
      if ([
        "stock_research", "stock_comparison", "analyst_expectations",
        "event_timeline", "shareholder_structure", "business_structure",
        "financial_drivers", "earnings_quality", "research_priority",
        "research_actions", "research_outcome", "research_tracking",
        "visual_research"
      ].includes(intent)) return "stock";
      if (/成交额|涨跌家数|普跌|结构性行情|大盘|主要指数|(A股|美股|港股|日股|韩股|欧股|伦敦金).{0,12}(收盘|市场|指数|涨跌|成交)/.test(text)) return "market";
      if (/大盘|指数|成交额|涨跌家数|普跌|结构性行情|A股|美股|港股|日股|韩股|欧股|伦敦金/.test(text)) return "market";
      if (/个股|股票|公司|行业|财报|公告|估值|股东|[036]\d{5}/.test(text)) return "stock";
      return "other";
    }
    function conversationScopeLabel(item) {
      return {stock: "个股", market: "大盘", screening: "选股", portfolio: "关注", funds: "基金理财", other: "其他"}[conversationScopeKey(item)] || "其他";
    }
    function conversationResearchTargets(item) {
      const output = [];
      for (const target of (item?.research_targets || [])) {
        const symbol = normalizedStockLookup(target?.symbol || target);
        if (!symbol || output.some(existing => existing.symbol === symbol)) continue;
        output.push({symbol, name: String(target?.name || symbol).trim() || symbol});
      }
      return output;
    }
    function conversationStockFilterOptions(items = []) {
      const options = new Map();
      for (const item of items) {
        if (conversationScopeKey(item) !== "stock") continue;
        for (const target of conversationResearchTargets(item)) {
          const current = options.get(target.symbol) || {...target, count: 0};
          current.count += 1;
          if (current.name === current.symbol && target.name !== target.symbol) current.name = target.name;
          options.set(target.symbol, current);
        }
      }
      return [...options.values()].sort((left, right) => right.count - left.count || left.name.localeCompare(right.name, "zh-CN"));
    }
    function syncConversationScopeOptions() {
      const baseOptions = [
        ["all", "全部"], ["stock", "个股"], ["market", "大盘"],
        ["screening", "选股"], ["funds", "基金理财"], ["portfolio", "关注"], ["other", "其他"]
      ];
      const stockOptions = conversationStockFilterOptions(state.conversations);
      const validValues = new Set(baseOptions.map(item => item[0]));
      stockOptions.forEach(item => validValues.add(`stock:${item.symbol}`));
      if (!validValues.has(state.conversationScope)) state.conversationScope = "all";
      for (const id of ["conversationScopeFilter", "conversationMobileScopeFilter"]) {
        const select = $(id);
        select.innerHTML = "";
        for (const [value, label] of baseOptions) {
          const option = document.createElement("option"); option.value = value; option.textContent = label; select.appendChild(option);
        }
        if (stockOptions.length) {
          const group = document.createElement("optgroup"); group.label = "具体股票";
          for (const item of stockOptions) {
            const option = document.createElement("option");
            option.value = `stock:${item.symbol}`;
            option.textContent = `${item.name} · ${item.count}`;
            group.appendChild(option);
          }
          select.appendChild(group);
        }
        select.value = state.conversationScope;
      }
    }
    function filteredConversationItems(items = []) {
      const query = String(state.conversationQuery || "")
        .trim()
        .toLocaleLowerCase("zh-CN")
        .replace(/\s+/g, "");
      const stockSymbol = state.conversationScope.startsWith("stock:")
        ? normalizedStockLookup(state.conversationScope.slice("stock:".length))
        : "";
      return items
        .filter(item => {
          if (state.conversationScope === "all") return true;
          if (stockSymbol) {
            return conversationScopeKey(item) === "stock"
              && conversationResearchTargets(item).some(target => target.symbol === stockSymbol);
          }
          return conversationScopeKey(item) === state.conversationScope;
        })
        .filter(item => {
          if (!query) return true;
          const targets = conversationResearchTargets(item).map(target => `${target.name} ${target.symbol}`).join(" ");
          const text = `${item.title || ""} ${item.last_message_preview || ""} ${conversationScopeLabel(item)} ${targets}`
            .toLocaleLowerCase("zh-CN")
            .replace(/\s+/g, "");
          return text.includes(query);
        });
    }
    const RECENT_CONVERSATION_TOPIC_LIMIT = 8;
    function conversationHistoryTopicKey(item) {
      const section = conversationDateSection(item?.updated_at);
      return `${section.key}:${conversationTopicKey(item)}`;
    }
    function conversationTopicCount(items = []) {
      return new Set(items.map(conversationHistoryTopicKey)).size;
    }
    function recentConversationItems(items = [], topicLimit = RECENT_CONVERSATION_TOPIC_LIMIT) {
      const selectedTopics = new Set();
      const activeItem = items.find(item => item.id === state.conversationId);
      const activeTopic = activeItem ? conversationHistoryTopicKey(activeItem) : "";
      for (const item of items) {
        const topic = conversationHistoryTopicKey(item);
        if (selectedTopics.has(topic)) continue;
        if (selectedTopics.size < topicLimit || topic === activeTopic) selectedTopics.add(topic);
      }
      return items.filter(item => selectedTopics.has(conversationHistoryTopicKey(item)));
    }
    function syncConversationFilterControls(filteredCount, displayState = {}) {
      const showFilters = state.conversations.length >= 8;
      $("conversationFilters").hidden = !showFilters;
      $("conversationMobileTools").hidden = !showFilters;
      syncConversationScopeOptions();
      for (const id of ["conversationSearch", "conversationMobileSearch"]) $(id).value = state.conversationQuery;
      const filtering = Boolean(state.conversationQuery.trim()) || state.conversationScope !== "all";
      $("conversationFilterMeta").textContent = filtering
        ? `显示 ${filteredCount} / ${state.conversations.length} 个对话`
        : displayState.limited
        ? `最近 ${displayState.topicCount || 0} 个主题 · 共 ${state.conversations.length} 个对话`
        : `${state.conversations.length} 个历史对话，可按标题或最近内容查找`;
    }
    function createConversationRow(item) {
      const row = document.createElement("div");
      row.className = `conversation-row${item.id === state.conversationId ? " active" : ""}`;
      const open = document.createElement("button"); open.className = "conversation-open"; open.type = "button";
      const title = document.createElement("span"); title.className = "conversation-title"; title.textContent = item.title || "新的研究对话";
      const meta = document.createElement("span"); meta.className = "conversation-meta";
      meta.textContent = `${item.message_count || 0} 条消息 · 更新 ${readableTime(item.updated_at)}`;
      open.title = `${title.textContent} · ${meta.textContent}`;
      open.append(title, meta);
      open.addEventListener("click", () => openConversation(item.id));
      const remove = document.createElement("button"); remove.className = "conversation-delete"; remove.type = "button"; remove.title = "归档对话"; remove.textContent = "归档";
      remove.setAttribute("aria-label", `归档对话：${title.textContent}`);
      remove.addEventListener("click", async event => {
        event.stopPropagation();
        if (!window.confirm(`归档“${title.textContent}”？对话会从最近列表移除。`)) return;
        await archiveConversation(item.id);
      });
      row.append(open, remove);
      return row;
    }
    function appendConversationGroups(container, items) {
      const sections = new Map();
      for (const item of items) {
        const section = conversationDateSection(item.updated_at);
        if (!sections.has(section.key)) sections.set(section.key, {...section, items: [], topics: new Map()});
        const current = sections.get(section.key);
        current.items.push(item);
        const topicKey = conversationTopicKey(item);
        if (!current.topics.has(topicKey)) current.topics.set(topicKey, []);
        current.topics.get(topicKey).push(item);
      }
      for (const section of sections.values()) {
        const group = document.createElement("section");
        group.className = "conversation-date-group";
        group.dataset.conversationDate = section.key;
        const heading = document.createElement("div"); heading.className = "conversation-date-heading";
        const headingLabel = document.createElement("span"); headingLabel.textContent = section.label;
        const headingCount = document.createElement("span"); headingCount.className = "conversation-date-count"; headingCount.textContent = `${section.items.length} 个`;
        heading.append(headingLabel, headingCount);
        group.appendChild(heading);
        for (const [topicKey, topicItems] of section.topics.entries()) {
          const stack = document.createElement("div"); stack.className = "conversation-topic-stack";
          stack.appendChild(createConversationRow(topicItems[0]));
          if (topicItems.length > 1) {
            const expansionKey = `${section.key}:${topicKey}`;
            const olderItems = topicItems.slice(1);
            const activeIsOlder = olderItems.some(item => item.id === state.conversationId);
            const expanded = activeIsOlder || state.expandedConversationTopics.has(expansionKey);
            const toggle = document.createElement("button"); toggle.className = "conversation-duplicate-toggle"; toggle.type = "button";
            const duplicates = document.createElement("div"); duplicates.className = "conversation-duplicates";
            for (const item of olderItems) duplicates.appendChild(createConversationRow(item));
            const syncExpansion = nextExpanded => {
              toggle.setAttribute("aria-expanded", String(nextExpanded));
              toggle.textContent = nextExpanded ? `收起 ${olderItems.length} 个同题旧对话` : `${olderItems.length} 个同题旧对话`;
              duplicates.hidden = !nextExpanded;
            };
            syncExpansion(expanded);
            toggle.addEventListener("click", () => {
              const nextExpanded = toggle.getAttribute("aria-expanded") !== "true";
              if (nextExpanded) state.expandedConversationTopics.add(expansionKey);
              else state.expandedConversationTopics.delete(expansionKey);
              syncExpansion(nextExpanded);
            });
            stack.append(toggle, duplicates);
          }
          group.appendChild(stack);
        }
        container.appendChild(group);
      }
    }
    function appendConversationHistoryToggle(container, {expanded, total}) {
      const button = document.createElement("button");
      button.className = "conversation-history-toggle";
      button.type = "button";
      button.setAttribute("aria-expanded", String(expanded));
      button.textContent = expanded ? "只看最近对话" : `查看全部历史（${total}）`;
      button.addEventListener("click", () => {
        state.conversationHistoryExpanded = !expanded;
        renderConversationList();
        container.scrollTop = 0;
      });
      container.appendChild(button);
    }
    function renderConversationList(items = null) {
      if (Array.isArray(items)) state.conversations = visibleConversationItems(items);
      const filteredItems = filteredConversationItems(state.conversations);
      const filtering = Boolean(state.conversationQuery.trim()) || state.conversationScope !== "all";
      const recentItems = recentConversationItems(filteredItems);
      const hasOlderHistory = !filtering && recentItems.length < filteredItems.length;
      const limited = hasOlderHistory && !state.conversationHistoryExpanded;
      const displayedItems = limited ? recentItems : filteredItems;
      syncConversationFilterControls(filteredItems.length, {
        limited,
        topicCount: conversationTopicCount(displayedItems),
      });
      for (const container of [$("conversationList"), $("agentHistoryList")]) {
        container.innerHTML = "";
        appendConversationGroups(container, displayedItems);
        if (!container.children.length) {
          container.innerHTML = state.conversations.length
            ? '<div class="conversation-filter-empty">没有匹配的历史对话<br>可以换一个关键词或研究类型</div>'
            : '<div class="knowledge-summary">还没有历史对话</div>';
        }
        if (hasOlderHistory) {
          appendConversationHistoryToggle(container, {
            expanded: state.conversationHistoryExpanded,
            total: filteredItems.length,
          });
        }
      }
      const switcher = $("conversationSwitcher");
      switcher.innerHTML = '<option value="">新的研究对话</option>';
      const activeItem = state.conversations.find(item => item.id === state.conversationId);
      const activePinned = activeItem && !filteredItems.some(item => item.id === activeItem.id);
      if (activePinned) {
        const option = document.createElement("option");
        option.value = activeItem.id;
        option.textContent = `当前对话 · ${activeItem.title || "新的研究对话"}`;
        switcher.appendChild(option);
      }
      if (filtering && !filteredItems.length) {
        const option = document.createElement("option");
        option.disabled = true;
        option.textContent = "没有匹配的历史对话";
        switcher.appendChild(option);
      }
      for (const item of filteredItems) {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = `${conversationScopeLabel(item)} · ${item.title || "新的研究对话"}`;
        switcher.appendChild(option);
      }
      switcher.value = state.conversationId || "";
      syncAgentResumeResearch();
      renderAgentResearchContext();
      renderAccountCenter();
    }
    async function openConversation(conversationId, activatePage = true, historyMode = null) {
      const draftRevision = state.chatDraftRevision;
      if (activatePage) activateWorkspace("agent", {historyMode: "none"});
      const data = await api(`/me/conversations/${encodeURIComponent(conversationId)}`);
      const nextEvaluationMode = data.quality_scope === "evaluation";
      const evaluationModeChanged = state.evaluationMode !== nextEvaluationMode;
      state.evaluationMode = nextEvaluationMode;
      if (evaluationModeChanged) {
        updateAgentMode();
        syncReviewModeVisibility();
        await loadConversations(false, false);
      }
      state.conversationId = data.id;
      state.conversationMessages = data.messages || [];
      const boundDeepStockSession = state.deepStockSessions.find(item => item.conversation_id === data.id) || null;
      const lastAssistant = [...state.conversationMessages].reverse().find(item => item.role === "assistant");
      const lastUser = [...state.conversationMessages].reverse().find(item => item.role === "user");
      state.agentContextMetadata = lastAssistant?.metadata || {};
      state.agentContextQuestion = lastUser?.content || data.title || "";
      setAgentProcessExpanded(false);
      $("conversationTitle").textContent = data.title || "金融研究 Agent";
      $("messages").innerHTML = "";
      if ((data.messages || []).length) {
        const freshness = document.createElement("div");
        freshness.className = "history-freshness";
        freshness.textContent = `历史回答保留生成时的证据快照（最近更新 ${readableTime(data.updated_at)}）；涉及当日行情，请直接追问“用最新数据重新分析”。`;
        $("messages").appendChild(freshness);
      }
      renderDiagnosisPlaceholder();
      if (!(data.messages || []).length) {
        addMessage(
          "agent",
          boundDeepStockSession
            ? `已关联${boundDeepStockSession.name || boundDeepStockSession.symbol}的长期研究空间。下方已经准备好当前阶段问题，你可以直接发送，也可以改成自己最关心的问法。`
            : currentWelcomeMessage()
        );
      }
      for (const message of (data.messages || [])) {
        addMessage(message.role === "assistant" ? "agent" : "user", message.content, false, message.metadata);
      }
      if ((data.messages || []).length) await syncDiagnosisFromConversation(data.messages || []);
      else if (boundDeepStockSession?.symbol) {
        state.agentContextMetadata = {symbol: boundDeepStockSession.symbol, intent: "stock_research"};
        state.agentContextQuestion = boundDeepStockSession.next_question || data.title || "";
        await loadStockDiagnosis(boundDeepStockSession.symbol);
        if (boundDeepStockSession.next_question && !$("chatInput").value.trim()) {
          setChatInputDraft(boundDeepStockSession.next_question, {
            expectedRevision: draftRevision
          });
        }
      }
      renderConversationList(state.conversations);
      clearImageAttachment();
      await loadMemoryCandidates();
      if (state.workspacePage === "agent" || stockAgentIsEmbedded()) $("chatInput").focus();
      if (state.workspacePage === "agent") syncWorkspaceUrl(historyMode || (activatePage ? "push" : "replace"));
      else if (stockAgentIsEmbedded()) syncWorkspaceUrl(historyMode || "replace");
      syncAgentEntryHubVisibility();
    }
