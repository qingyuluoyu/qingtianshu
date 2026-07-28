function fundKindLabel(value) {
      return value === "etf" ? "场内 ETF" : "场外基金";
    }

    function fundAssetLabel(value) {
      return {
        equity_index: "股票指数",
        equity: "主动股票",
        fixed_income: "债券与固收",
        mixed: "混合资产",
        money_market: "货币市场",
        overseas: "海外资产",
        commodity: "商品",
        reit: "REITs",
        other: "其他"
      }[value] || "未分类";
    }

    function fundReturn(value) {
      if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
      const number = Number(value);
      return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
    }

    function latestRiskProfileVersion(packet = state.riskProfile) {
      return Math.max(
        Number(packet?.draft?.version_no || 0),
        Number(packet?.confirmed?.version_no || 0)
      );
    }

    function riskProfileAnswerSource(packet = state.riskProfile) {
      return packet?.draft?.answers || packet?.confirmed?.answers || {};
    }

    function riskProfileCompletion() {
      const questions = state.riskProfile?.questions || [];
      const selectedKeys = new Set(
        [...document.querySelectorAll('#riskProfileQuestions input[data-risk-key]:checked')]
          .map(input => input.dataset.riskKey)
          .filter(Boolean)
      );
      const missing = questions.filter(question => !selectedKeys.has(question.key));
      return {answered: questions.length - missing.length, total: questions.length, missing};
    }

    function setRiskProfileStep(id, status) {
      const node = $(id);
      node.classList.toggle("active", status === "active");
      node.classList.toggle("complete", status === "complete");
    }

    function syncRiskProfileProgress({focusFirstMissing = false} = {}) {
      const completion = riskProfileCompletion();
      const total = completion.total || 7;
      const answered = Math.min(completion.answered, total);
      $("riskProfileProgressText").textContent = `已回答 ${answered}/${total}`;
      $("riskProfileProgressBar").setAttribute("aria-valuemax", String(total));
      $("riskProfileProgressBar").setAttribute("aria-valuenow", String(answered));
      $("riskProfileProgressBar").querySelector("span").style.width = `${total ? (answered / total) * 100 : 0}%`;

      for (const fieldset of document.querySelectorAll(".risk-profile-question")) {
        const isAnswered = !completion.missing.some(question => question.key === fieldset.dataset.riskKey);
        fieldset.classList.toggle("answered", isAnswered);
        if (isAnswered) fieldset.classList.remove("missing");
      }

      const packet = state.riskProfile || {};
      const answersComplete = Boolean(total) && answered === total;
      const saved = Boolean(packet.draft) && !state.riskProfileDirty;
      const confirmed = Boolean(packet.confirmed) && !packet.draft && !state.riskProfileDirty;
      setRiskProfileStep("riskProfileStepAnswer", answersComplete ? "complete" : "active");
      setRiskProfileStep("riskProfileStepSave", saved || confirmed ? "complete" : (answersComplete ? "active" : "pending"));
      setRiskProfileStep("riskProfileStepConfirm", confirmed ? "complete" : (saved ? "active" : "pending"));

      $("riskProfileNextStep").textContent = completion.missing.length
        ? `还差 ${completion.missing.length} 题，下一题：${completion.missing[0].label}`
        : (state.riskProfileDirty
          ? "答案已完整，请保存并核对"
          : (packet.draft
            ? "草稿已保存，请核对后确认是否让 AI 使用"
            : (packet.confirmed
              ? "画像已确认，可以让金融顾问结合这些事实解释产品条件"
              : "答案已完整，请保存并核对")));

      if (focusFirstMissing && completion.missing.length) {
        const fieldset = document.querySelector(`.risk-profile-question[data-risk-key="${completion.missing[0].key}"]`);
        if (fieldset) {
          fieldset.classList.add("missing");
          fieldset.scrollIntoView({behavior: "smooth", block: "center"});
          const input = fieldset.querySelector("input[type=radio]");
          requestAnimationFrame(() => input?.focus({preventScroll: true}));
        }
      }
      return completion;
    }

    function openRiskProfileAdvisor() {
      startNewConversation(true, "push");
      $("chatInput").value = "请结合我已经确认的风险画像，帮我梳理哪些基金、ETF或低波动工具更适合我优先比较。先告诉我你已经知道的条件，再只问仍会改变判断的关键信息；说明每类产品的主要亏损方式、流动性和费用边界。不要替我直接决定产品，也不要给收益承诺。";
      $("chatInput").focus();
    }

    function renderRiskProfileConfirmed(profile) {
      const host = $("riskProfileConfirmed");
      host.innerHTML = "";
      host.hidden = !profile;
      if (!profile) return;
      const derived = profile.derived || {};
      const title = document.createElement("strong");
      title.textContent = derived.summary_label || "已确认个人画像";
      const meta = document.createElement("span");
      meta.textContent = `版本 ${profile.version_no || "—"} · 确认于 ${readableTime(profile.confirmed_at || profile.updated_at)}`;
      const copy = document.createElement("p");
      const constraints = derived.constraints || [];
      copy.textContent = constraints.length
        ? `需要优先核对：${constraints.join("；")}`
        : "当前没有从问卷中识别出额外限制，但仍需结合具体产品事实逐项判断。";
      const actions = document.createElement("div");
      actions.className = "risk-profile-confirmed-actions";
      const next = document.createElement("span");
      next.textContent = "下一步：带着这份画像询问具体产品，不会自动发送问题。";
      const ask = document.createElement("button");
      ask.id = "riskProfileAskAdvisor";
      ask.type = "button";
      ask.className = "btn primary";
      ask.textContent = "去问金融顾问";
      ask.addEventListener("click", openRiskProfileAdvisor);
      actions.append(next, ask);
      host.append(title, meta, copy, actions);
    }

    function renderRiskProfile(packet) {
      state.riskProfile = packet;
      state.riskProfileDirty = false;
      const questions = $("riskProfileQuestions");
      questions.innerHTML = "";
      const answers = riskProfileAnswerSource(packet);
      for (const [index, question] of (packet.questions || []).entries()) {
        const fieldset = document.createElement("fieldset");
        fieldset.className = "risk-profile-question";
        fieldset.dataset.riskKey = question.key;
        const legend = document.createElement("legend");
        const number = document.createElement("span"); number.textContent = String(index + 1);
        const label = document.createElement("strong"); label.textContent = question.label;
        legend.append(number, label);
        const help = document.createElement("p"); help.textContent = question.help || "";
        const options = document.createElement("div"); options.className = "risk-profile-options";
        for (const option of (question.options || [])) {
          const choice = document.createElement("label"); choice.className = "risk-profile-option";
          const input = document.createElement("input");
          input.type = "radio";
          input.name = `risk_${question.key}`;
          input.value = option.value;
          input.checked = answers[question.key] === option.value;
          input.dataset.riskKey = question.key;
          const copy = document.createElement("span"); copy.textContent = option.label;
          choice.append(input, copy); options.appendChild(choice);
        }
        fieldset.append(legend, help, options); questions.appendChild(fieldset);
      }
      const draft = packet.draft;
      const confirmed = packet.confirmed;
      $("riskProfileState").className = `risk-profile-state ${draft ? "draft" : (confirmed ? "confirmed" : "")}`;
      $("riskProfileState").textContent = draft
        ? `草稿 v${draft.version_no} · 尚未生效`
        : (confirmed ? `已确认 v${confirmed.version_no}` : "尚未填写");
      $("riskProfileConfirm").disabled = !draft;
      $("riskProfileStatus").className = "risk-profile-status";
      $("riskProfileStatus").textContent = draft
        ? "草稿已保存，但尚未用于 AI。请核对后再确认。"
        : (confirmed ? "当前已确认版本会用于有条件的适合性解释。修改答案后需重新保存和确认。" : "请先完成 7 个问题；保存后仍需你再次确认。");
      $("riskProfileBoundary").textContent = packet.boundary || "聊天内容不会自动改写正式画像。";
      renderRiskProfileConfirmed(confirmed);
      syncRiskProfileProgress();
    }

    async function loadRiskProfile(options = {}) {
      if (state.riskProfileLoading) return;
      if (state.riskProfile && !options.force) {
        renderRiskProfile(state.riskProfile);
        return;
      }
      state.riskProfileLoading = true;
      $("riskProfileStatus").textContent = "正在读取你的风险画像…";
      try {
        renderRiskProfile(await api("/me/risk-profile"));
      } catch (error) {
        $("riskProfileQuestions").innerHTML = '<div class="empty">风险问卷暂时没有加载，请稍后重试。</div>';
        $("riskProfileStatus").className = "risk-profile-status error";
        $("riskProfileStatus").textContent = error.message || "风险画像暂时无法读取。";
      } finally {
        state.riskProfileLoading = false;
      }
    }

    function collectRiskProfileAnswers() {
      const completion = syncRiskProfileProgress({focusFirstMissing: true});
      if (completion.missing.length) {
        throw new Error(`还有 ${completion.missing.length} 题未回答，请先完成高亮问题：${completion.missing[0].label}`);
      }
      const answers = {};
      for (const question of (state.riskProfile?.questions || [])) {
        const selected = document.querySelector(`input[name="risk_${question.key}"]:checked`);
        answers[question.key] = selected.value;
      }
      return answers;
    }

    async function saveRiskProfileDraft() {
      const button = $("riskProfileSave");
      button.disabled = true;
      $("riskProfileConfirm").disabled = true;
      $("riskProfileStatus").className = "risk-profile-status";
      $("riskProfileStatus").textContent = "正在保存草稿；保存后仍不会自动用于 AI…";
      try {
        const draft = await api("/me/risk-profile/draft", {
          method: "PUT",
          body: JSON.stringify({
            base_version: latestRiskProfileVersion(),
            answers: collectRiskProfileAnswers()
          })
        });
        state.riskProfile = {...state.riskProfile, draft};
        renderRiskProfile(state.riskProfile);
        $("riskProfileStatus").textContent = "草稿已保存。请再次核对，确认后才会用于 AI。";
      } catch (error) {
        $("riskProfileStatus").className = "risk-profile-status error";
        $("riskProfileStatus").textContent = error.message || "风险画像草稿保存失败。";
      } finally {
        button.disabled = false;
      }
    }

    async function confirmRiskProfile() {
      const draft = state.riskProfile?.draft;
      if (!draft || state.riskProfileDirty) return;
      const button = $("riskProfileConfirm");
      button.disabled = true;
      $("riskProfileStatus").className = "risk-profile-status";
      $("riskProfileStatus").textContent = "正在确认；确认后 Agent 才能读取这组答案…";
      try {
        await api("/me/risk-profile/confirm", {
          method: "POST",
          body: JSON.stringify({version_no: draft.version_no})
        });
        state.riskProfile = null;
        await loadRiskProfile({force: true});
        $("riskProfileStatus").textContent = "已由你确认。后续适合性回答会引用该版本，并明确说明边界。";
      } catch (error) {
        $("riskProfileStatus").className = "risk-profile-status error";
        $("riskProfileStatus").textContent = error.message || "风险画像确认失败。";
      }
    }

    function exactFundCandidate(query, items) {
      const normalized = String(query || "").normalize("NFKC").trim().toUpperCase();
      const exact = items.filter(item => normalized === String(item.code || "").toUpperCase()
        || normalized === String(item.name || "").normalize("NFKC").trim().toUpperCase());
      if (exact.length === 1) return exact[0];
      if (!exact.length && items.length === 1) return items[0];
      return null;
    }

    function renderFundChoices(slot, query, items) {
      const host = $("fundComparisonChoices");
      host.innerHTML = "";
      host.hidden = false;
      const heading = document.createElement("strong");
      heading.textContent = `“${query}”有多个结果，请选择：`;
      host.appendChild(heading);
      for (const item of items.slice(0, 6)) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "fund-choice";
        button.textContent = `${item.name}（${item.code}） · ${item.fund_type || fundKindLabel(item.product_kind)}`;
        button.addEventListener("click", () => {
          $(slot === "first" ? "fundComparisonFirst" : "fundComparisonSecond").value = item.code;
          host.hidden = true;
          host.innerHTML = "";
          $("fundComparisonStatus").textContent = `已选择 ${item.name}（${item.code}），请继续比较。`;
        });
        host.appendChild(button);
      }
    }

    async function resolveFundInput(value, slot) {
      const query = String(value || "").normalize("NFKC").trim();
      if (!query) throw new Error("请填写两个要比较的基金或 ETF。 ");
      if (/^\d{6}$/.test(query)) return {code: query, name: query};
      const data = await api(`/fund-products/search?q=${encodeURIComponent(query)}&limit=8`);
      const items = data.items || [];
      if (!items.length) throw new Error(`没有找到“${query}”对应的基金或 ETF，请换用完整名称或 6 位代码。`);
      const exact = exactFundCandidate(query, items);
      if (exact) return exact;
      renderFundChoices(slot, query, items);
      throw new Error("请选择一个明确产品后再比较，系统不会静默替你选择。");
    }

    function appendFundMetric(host, label, value) {
      const row = document.createElement("div"); row.className = "fund-product-metric";
      const name = document.createElement("span"); name.textContent = label;
      const content = document.createElement("strong"); content.textContent = value;
      row.append(name, content); host.appendChild(row);
    }

    function renderFundProductCard(product) {
      const card = document.createElement("article"); card.className = "fund-product-card";
      const heading = document.createElement("div"); heading.className = "fund-product-heading";
      const identity = document.createElement("div");
      const name = document.createElement("strong"); name.textContent = product.name || product.code;
      const code = document.createElement("span"); code.textContent = `${product.code} · ${fundKindLabel(product.product_kind)} · ${fundAssetLabel(product.asset_class)}`;
      identity.append(name, code);
      const status = document.createElement("span"); status.className = "fund-product-status"; status.textContent = product.data_status === "stale" ? "保留快照" : "当前事实";
      heading.append(identity, status); card.appendChild(heading);
      const metrics = document.createElement("div"); metrics.className = "fund-product-metrics";
      appendFundMetric(metrics, "最新净值", product.nav == null ? "—" : `${numeric(product.nav)} · ${product.nav_date || "日期未知"}`);
      if (product.product_kind === "etf") {
        appendFundMetric(metrics, "场内成交价", product.live_quote?.price == null ? "暂未取得" : `${numeric(product.live_quote.price)} · ${fundReturn(product.live_quote.pct_change)}`);
      }
      appendFundMetric(metrics, "近1月", fundReturn(product.returns?.one_month_pct));
      appendFundMetric(metrics, "近3月", fundReturn(product.returns?.three_month_pct));
      appendFundMetric(metrics, "近6月", fundReturn(product.returns?.six_month_pct));
      appendFundMetric(metrics, "近1年", fundReturn(product.returns?.one_year_pct));
      appendFundMetric(metrics, "规模", compactNumber(product.net_assets_cny, "元"));
      appendFundMetric(metrics, "申购 / 赎回", `${product.purchase_status || "未知"} / ${product.redemption_status || "未知"}`);
      card.appendChild(metrics);
      return card;
    }

    function renderFundComparison(packet) {
      state.fundComparison = packet;
      const host = $("fundComparisonResult");
      host.innerHTML = "";
      host.hidden = false;
      const summary = document.createElement("div"); summary.className = "fund-comparison-summary";
      const title = document.createElement("strong"); title.textContent = "同口径产品事实";
      const meta = document.createElement("span");
      meta.textContent = `净值日期：${(packet.as_of?.nav_dates || []).join("、") || "待核验"} · 历史收益不代表未来表现`;
      summary.append(title, meta); host.appendChild(summary);
      const grid = document.createElement("div"); grid.className = "fund-product-grid";
      for (const product of (packet.products || [])) grid.appendChild(renderFundProductCard(product));
      host.appendChild(grid);
      const boundary = document.createElement("p"); boundary.className = "fund-comparison-boundary";
      boundary.textContent = packet.boundary || "产品事实比较不等于基金评级或推荐。";
      const ask = document.createElement("button"); ask.type = "button"; ask.className = "btn"; ask.textContent = "让 AI 结合我的情况解读";
      ask.addEventListener("click", async () => {
        const products = (packet.products || []).map(item => `${item.name}（${item.code}）`).join("和");
        await sendChat(`请基于刚取得的当前产品事实，比较${products}。先说明底层资产、交易方式、净值日期、相同窗口历史收益、规模和费用边界，再结合我已经确认的风险画像说明各自需要满足的条件；如果我还没有确认画像，就明确告诉我还需要补充哪些事实。不要替我选择唯一产品，不要给收益承诺或买卖指令。`);
      });
      host.append(boundary, ask);
    }

    async function runFundComparison() {
      const button = $("fundComparisonSubmit");
      const status = $("fundComparisonStatus");
      button.disabled = true;
      status.className = "agent-entry-status";
      status.textContent = "正在识别产品并读取最新净值、收益窗口、规模与状态…";
      $("fundComparisonResult").hidden = true;
      try {
        const first = await resolveFundInput($("fundComparisonFirst").value, "first");
        const second = await resolveFundInput($("fundComparisonSecond").value, "second");
        if (first.code === second.code) throw new Error("请选择两个不同的基金或 ETF。 ");
        $("fundComparisonFirst").value = first.code;
        $("fundComparisonSecond").value = second.code;
        const packet = await api(`/fund-products?codes=${encodeURIComponent(`${first.code},${second.code}`)}`);
        renderFundComparison(packet);
        status.textContent = "比较已完成。ETF 场内成交价与基金净值已分开显示。";
      } catch (error) {
        status.className = "agent-entry-status error";
        status.textContent = error.message || "基金与 ETF 比较暂时没有完成。";
      } finally {
        button.disabled = false;
      }
    }

    $("riskProfileForm").addEventListener("submit", event => {
      event.preventDefault();
      void saveRiskProfileDraft();
    });
    $("riskProfileQuestions").addEventListener("change", () => {
      state.riskProfileDirty = true;
      $("riskProfileConfirm").disabled = true;
      $("riskProfileState").className = "risk-profile-state draft";
      $("riskProfileState").textContent = "有修改 · 尚未保存";
      $("riskProfileStatus").className = "risk-profile-status attention";
      $("riskProfileStatus").textContent = "答案已修改。请先保存草稿，再确认是否用于 AI。";
      syncRiskProfileProgress();
    });
    $("riskProfileConfirm").addEventListener("click", () => { void confirmRiskProfile(); });
    $("fundComparisonForm").addEventListener("submit", event => {
      event.preventDefault();
      void runFundComparison();
    });
