function positionIdempotencyKey(prefix) {
      const random = globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      return `${prefix}-${random}`;
    }

    function localDateTimeValue(date = new Date()) {
      const offset = date.getTimezoneOffset() * 60000;
      return new Date(date.getTime() - offset).toISOString().slice(0, 16);
    }

    function localDateValue(date = new Date()) {
      const offset = date.getTimezoneOffset() * 60000;
      return new Date(date.getTime() - offset).toISOString().slice(0, 10);
    }

    function positionField(labelText, input) {
      const label = document.createElement("label");
      if (input.classList.contains("position-form-wide") || input.classList.contains("form-wide")) label.classList.add("position-form-wide");
      const text = document.createElement("span"); text.textContent = labelText;
      label.append(text, input); return label;
    }

    async function refreshPositionWorkspace(symbol) {
      await loadDeepStockOverview(symbol);
      activateStockSpaceTab("tasks");
    }

    function showPositionOpeningForm(host, symbol) {
      if (host.querySelector(".position-entry-form")) return;
      const form = document.createElement("form"); form.className = "position-entry-form";
      const openingIdempotencyKey = positionIdempotencyKey("opening");
      const asOf = document.createElement("input"); asOf.type = "date"; asOf.required = true; asOf.value = localDateValue();
      const quantity = document.createElement("input"); quantity.inputMode = "decimal"; quantity.required = true; quantity.placeholder = "例如 1000";
      const cost = document.createElement("input"); cost.inputMode = "decimal"; cost.required = true; cost.placeholder = "每股成本，例如 37.50";
      const fees = document.createElement("input"); fees.inputMode = "decimal"; fees.placeholder = "不知道可留空，不会按 0 处理";
      const note = document.createElement("textarea"); note.className = "position-form-wide"; note.placeholder = "可选：数据来源、补录原因或费用口径";
      const status = document.createElement("div"); status.className = "position-form-status"; status.textContent = "期初持仓每个股票空间只录入一次；保存后由流水派生快照。";
      const actions = document.createElement("div"); actions.className = "position-form-actions";
      const save = document.createElement("button"); save.type = "submit"; save.className = "btn primary"; save.textContent = "保存期初持仓";
      const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "btn"; cancel.textContent = "取消"; cancel.addEventListener("click", () => form.remove());
      actions.append(save, cancel);
      form.append(positionField("基准日期", asOf), positionField("持仓数量", quantity), positionField("每股成本", cost), positionField("已知费用", fees), positionField("备注", note), status, actions);
      form.addEventListener("submit", async event => {
        event.preventDefault(); save.disabled = true; cancel.disabled = true; status.textContent = "正在保存并重算持仓…";
        try {
          await api(`/v1/stocks/${encodeURIComponent(symbol)}/position/opening`, {
            method: "POST",
            headers: {"Idempotency-Key": openingIdempotencyKey},
            body: JSON.stringify({as_of_date: asOf.value, quantity: quantity.value.trim(), cost_price: cost.value.trim(), fees: fees.value.trim() || null, note: note.value.trim() || null})
          });
          await refreshPositionWorkspace(symbol);
        } catch (error) { save.disabled = false; cancel.disabled = false; status.textContent = error.message || "期初持仓未保存，请检查输入。"; }
      });
      host.appendChild(form); quantity.focus();
    }

    function showPositionOperationForm(host, symbol, preferredPlanId = null) {
      if (host.querySelector(".position-entry-form")) return;
      const form = document.createElement("form"); form.className = "position-entry-form";
      const operationIdempotencyKey = positionIdempotencyKey("operation");
      const type = document.createElement("select");
      [["buy", "首次买入"], ["add", "增加持仓"], ["reduce", "减少持仓"], ["sell", "卖出"]].forEach(([value, label]) => { const option = document.createElement("option"); option.value = value; option.textContent = label; type.appendChild(option); });
      const preferredPlan = (state.stockActionPlans[symbol] || []).find(item => ["saved", "partially_executed"].includes(item.status) && String(item.id) === String(preferredPlanId));
      if (preferredPlan?.action_type) type.value = preferredPlan.action_type;
      const plan = document.createElement("select");
      const refreshPlanOptions = () => {
        const selectedPlanId = plan.value || (preferredPlanId == null ? "" : String(preferredPlanId));
        plan.innerHTML = "";
        const noPlan = document.createElement("option"); noPlan.value = ""; noPlan.textContent = "不关联计划"; plan.appendChild(noPlan);
        (state.stockActionPlans[symbol] || []).filter(item => ["saved", "partially_executed"].includes(item.status) && item.action_type === type.value).forEach(item => {
          const option = document.createElement("option"); option.value = item.id; option.textContent = `${actionPlanTypeLabel(item.action_type)} · ${item.trigger_text || actionPlanTargetText(item)}`; plan.appendChild(option);
        });
        plan.value = [...plan.options].some(option => option.value === selectedPlanId) ? selectedPlanId : "";
      };
      type.addEventListener("change", refreshPlanOptions);
      refreshPlanOptions();
      const operatedAt = document.createElement("input"); operatedAt.type = "datetime-local"; operatedAt.required = true; operatedAt.value = localDateTimeValue();
      const price = document.createElement("input"); price.inputMode = "decimal"; price.required = true; price.placeholder = "成交价格";
      const quantity = document.createElement("input"); quantity.inputMode = "decimal"; quantity.required = true; quantity.placeholder = "成交数量";
      const fees = document.createElement("input"); fees.inputMode = "decimal"; fees.placeholder = "不知道可留空";
      const reason = document.createElement("textarea"); reason.className = "position-form-wide"; reason.required = true; reason.placeholder = "记录当时的事实和理由；请勿填写系统生成的买卖建议";
      const status = document.createElement("div"); status.className = "position-form-status"; status.textContent = "操作只追加流水；只有减仓或卖出会创建交易复盘，并需等待 3 个后续交易日数据；买入和加仓不会创建复盘。错误记录通过修订保留历史，不直接覆盖。";
      const actions = document.createElement("div"); actions.className = "position-form-actions";
      const save = document.createElement("button"); save.type = "submit"; save.className = "btn primary"; save.textContent = "保存操作";
      const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "btn"; cancel.textContent = "取消"; cancel.addEventListener("click", () => form.remove());
      actions.append(save, cancel);
      form.append(positionField("操作类型", type), positionField("关联已保存计划", plan), positionField("操作时间", operatedAt), positionField("成交价格", price), positionField("成交数量", quantity), positionField("已知费用", fees), positionField("操作事实与理由", reason), status, actions);
      form.addEventListener("submit", async event => {
        event.preventDefault(); save.disabled = true; cancel.disabled = true; status.textContent = "正在保存流水并生成新快照…";
        try {
          await api(`/v1/stocks/${encodeURIComponent(symbol)}/operations`, {
            method: "POST",
            headers: {"Idempotency-Key": operationIdempotencyKey},
            body: JSON.stringify({operation_type: type.value, plan_id: plan.value || null, operated_at: new Date(operatedAt.value).toISOString(), price: price.value.trim(), quantity: quantity.value.trim(), fees: fees.value.trim() || null, reason_text: reason.value.trim()})
          });
          await refreshPositionWorkspace(symbol);
        } catch (error) { save.disabled = false; cancel.disabled = false; status.textContent = error.message || "操作未保存，请检查输入。"; }
      });
      host.appendChild(form); price.focus();
    }

    function showPositionAdjustmentForm(host, symbol) {
      if (host.querySelector(".position-entry-form")) return;
      const form = document.createElement("form"); form.className = "position-entry-form";
      const adjustmentIdempotencyKey = positionIdempotencyKey("adjustment");
      const type = document.createElement("select");
      [["corporate_action", "送转、拆并等公司行动"], ["quantity_correction", "数量调整"], ["cost_correction", "成本调整"], ["other", "其他非交易调整"]].forEach(([value, label]) => { const option = document.createElement("option"); option.value = value; option.textContent = label; type.appendChild(option); });
      const effectiveAt = document.createElement("input"); effectiveAt.type = "datetime-local"; effectiveAt.required = true; effectiveAt.value = localDateTimeValue();
      const quantity = document.createElement("input"); quantity.inputMode = "decimal"; quantity.value = "0"; quantity.placeholder = "增加为正，减少为负";
      const cost = document.createElement("input"); cost.inputMode = "decimal"; cost.value = "0"; cost.placeholder = "成本增加为正，减少为负";
      const reason = document.createElement("textarea"); reason.className = "position-form-wide"; reason.required = true; reason.placeholder = "说明调整原因和口径";
      const evidence = document.createElement("textarea"); evidence.className = "position-form-wide"; evidence.placeholder = "可选：公告、回单或人工核对依据";
      const status = document.createElement("div"); status.className = "position-form-status"; status.textContent = "非交易调整不会伪装成买卖记录；数量和成本至少一项必须变化。";
      const actions = document.createElement("div"); actions.className = "position-form-actions";
      const save = document.createElement("button"); save.type = "submit"; save.className = "btn primary"; save.textContent = "保存调整";
      const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "btn"; cancel.textContent = "取消"; cancel.addEventListener("click", () => form.remove());
      actions.append(save, cancel);
      form.append(positionField("调整类型", type), positionField("生效时间", effectiveAt), positionField("数量变化", quantity), positionField("成本变化", cost), positionField("调整原因", reason), positionField("核对依据", evidence), status, actions);
      form.addEventListener("submit", async event => {
        event.preventDefault(); save.disabled = true; cancel.disabled = true; status.textContent = "正在保存调整并重算持仓…";
        try {
          await api(`/v1/stocks/${encodeURIComponent(symbol)}/position-adjustments`, {
            method: "POST",
            headers: {"Idempotency-Key": adjustmentIdempotencyKey},
            body: JSON.stringify({adjustment_type: type.value, effective_at: new Date(effectiveAt.value).toISOString(), quantity_delta: quantity.value.trim() || "0", cost_delta: cost.value.trim() || "0", reason_text: reason.value.trim(), evidence_text: evidence.value.trim() || null})
          });
          await refreshPositionWorkspace(symbol);
        } catch (error) { save.disabled = false; cancel.disabled = false; status.textContent = error.message || "调整未保存，请检查输入。"; }
      });
      host.appendChild(form); reason.focus();
    }

    function showPositionRevisionForm(host, symbol, operation) {
      if (host.querySelector(".position-entry-form")) return;
      const form = document.createElement("form"); form.className = "position-entry-form";
      const revisionIdempotencyKey = positionIdempotencyKey("revision");
      const price = document.createElement("input"); price.inputMode = "decimal"; price.required = true; price.value = operation.price || "";
      const quantity = document.createElement("input"); quantity.inputMode = "decimal"; quantity.required = true; quantity.value = operation.quantity || "";
      const fees = document.createElement("input"); fees.inputMode = "decimal"; fees.value = operation.fees ?? ""; fees.placeholder = "不知道可留空";
      const reason = document.createElement("textarea"); reason.className = "position-form-wide"; reason.required = true; reason.placeholder = "说明为什么需要修正，并保留回单或核对依据";
      const status = document.createElement("div"); status.className = "position-form-status"; status.textContent = `当前修订版本 ${operation.current_revision || 0}；原流水不会被覆盖。`;
      const actions = document.createElement("div"); actions.className = "position-form-actions";
      const save = document.createElement("button"); save.type = "submit"; save.className = "btn primary"; save.textContent = "保存修订";
      const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "btn"; cancel.textContent = "取消"; cancel.addEventListener("click", () => form.remove());
      actions.append(save, cancel);
      form.append(positionField("修正价格", price), positionField("修正数量", quantity), positionField("修正费用", fees), positionField("修正原因", reason), status, actions);
      form.addEventListener("submit", async event => {
        event.preventDefault(); save.disabled = true; cancel.disabled = true; status.textContent = "正在保存修订并重放全部流水…";
        try {
          await api(`/v1/operations/${encodeURIComponent(operation.id)}`, {
            method: "PATCH",
            headers: {"Idempotency-Key": revisionIdempotencyKey},
            body: JSON.stringify({base_revision: operation.current_revision || 0, price: price.value.trim(), quantity: quantity.value.trim(), fees: fees.value.trim() || null, reason_text: reason.value.trim()})
          });
          await refreshPositionWorkspace(symbol);
        } catch (error) { save.disabled = false; cancel.disabled = false; status.textContent = error.message || "修订未保存，请检查是否已有更新。"; }
      });
      host.appendChild(form); reason.focus();
    }

    function renderPositionWorkspace(symbol, workspace) {
      const section = document.createElement("section"); section.className = "position-workspace";
      const position = workspace?.position_snapshot || {available: false, status: "not_configured"};
      const head = document.createElement("div"); head.className = "position-workspace-head";
      const copyWrap = document.createElement("div");
      const title = document.createElement("div"); title.className = "position-workspace-title"; title.textContent = "持仓事实与操作流水";
      const copy = document.createElement("div"); copy.className = "position-workspace-copy";
      copy.textContent = position.available ? "当前持仓由期初、操作和调整流水派生，不能直接编辑结果。" : "关系标签不等于真实持仓；录入期初数量和成本后才开始对账。";
      copyWrap.append(title, copy);
      const buttons = document.createElement("div"); buttons.className = "stock-workspace-actions";
      if (!position.available) {
        const opening = document.createElement("button"); opening.type = "button"; opening.className = "btn primary"; opening.textContent = "录入期初持仓"; opening.addEventListener("click", () => showPositionOpeningForm(section, symbol)); buttons.appendChild(opening);
      } else {
        const record = document.createElement("button"); record.type = "button"; record.className = "btn primary"; record.textContent = "记录操作"; record.addEventListener("click", () => showPositionOperationForm(section, symbol));
        const adjust = document.createElement("button"); adjust.type = "button"; adjust.className = "btn"; adjust.textContent = "非交易调整"; adjust.addEventListener("click", () => showPositionAdjustmentForm(section, symbol));
        buttons.append(record, adjust);
      }
      head.append(copyWrap, buttons); section.appendChild(head);
      if (!position.available || !position.current) return section;
      const current = position.current;
      const metrics = document.createElement("div"); metrics.className = "position-metrics";
      [["持仓数量", current.quantity], ["移动平均成本", current.average_cost || "已清仓"], ["当前成本总额", current.cost_basis], ["已实现净结果", current.realized_net_pnl ?? "费用待补"]].forEach(([labelText, value]) => {
        const card = document.createElement("div"); card.className = "position-metric";
        const label = document.createElement("span"); label.textContent = labelText;
        const strong = document.createElement("strong"); strong.textContent = value ?? "—";
        card.append(label, strong); metrics.appendChild(card);
      });
      section.appendChild(metrics);
      const warnings = current.warnings || [];
      if (warnings.length) { const warning = document.createElement("div"); warning.className = "position-workspace-copy"; warning.textContent = warnings.join(" "); section.appendChild(warning); }
      const operations = [...(position.operations || [])].reverse().slice(0, 4);
      if (operations.length) {
        const list = document.createElement("div"); list.className = "position-ledger-list";
        operations.forEach(item => {
          const row = document.createElement("div"); row.className = "position-ledger-item";
          const label = document.createElement("strong"); label.textContent = {buy: "买入", add: "增加持仓", reduce: "减少持仓", sell: "卖出"}[item.operation_type] || "操作";
          const detail = document.createElement("span"); detail.textContent = `${readableTime(item.operated_at)} · ${item.quantity} 股 × ${item.price}${item.fees == null ? " · 费用待补" : ` · 费用 ${item.fees}`}${item.current_revision ? ` · 修订 ${item.current_revision}` : ""}`;
          const right = document.createElement("div"); right.className = "stock-workspace-actions";
          const revise = document.createElement("button"); revise.type = "button"; revise.className = "btn"; revise.textContent = "修正"; revise.addEventListener("click", () => showPositionRevisionForm(section, symbol, item));
          right.append(detail, revise); row.append(label, right); list.appendChild(row);
        });
        section.appendChild(list);
      }
      return section;
    }

    function listPayloadItems(payload) {
      if (Array.isArray(payload)) return payload;
      return payload?.items || payload?.action_plans || payload?.trade_reviews || payload?.reviews || [];
    }

    function actionPlanStatusLabel(status) {
      return {
        draft: "草稿",
        checked: "已检查",
        saved: "已保存",
        partially_executed: "部分执行",
        executed: "已执行",
        cancelled: "已取消",
        expired: "已过期"
      }[status] || "计划";
    }

    function actionPlanTypeLabel(actionType) {
      return {buy: "买入", add: "增加持仓", reduce: "减少持仓", sell: "卖出", hold: "保持观察"}[actionType] || "自定义操作";
    }

    function actionPlanTargetText(plan) {
      return [
        plan.target_quantity != null ? `${plan.target_quantity} 股` : "",
        plan.target_amount != null ? `金额 ${plan.target_amount}` : "",
        plan.target_position_percent != null ? `目标仓位 ${plan.target_position_percent}%` : ""
      ].filter(Boolean).join(" · ") || "尚未填写数量、金额或仓位";
    }

    function friendlyStructuredText(value, fallback = "尚未形成") {
      if (value === null || value === undefined || value === "") return fallback;
      if (typeof value === "string" || typeof value === "number") return String(value);
      if (Array.isArray(value)) return value.map(item => friendlyStructuredText(item, "")).filter(Boolean).join("；") || fallback;
      for (const key of ["summary", "conclusion", "label", "text", "description"]) {
        if (value[key]) return friendlyStructuredText(value[key], fallback);
      }
      return Object.entries(value).slice(0, 6).map(([key, item]) => `${key}：${friendlyStructuredText(item, "—")}`).join("；") || fallback;
    }

    function actionPlanCheckText(checkResult) {
      if (!checkResult || typeof checkResult !== "object") return "";
      if (!checkResult.passed) {
        const missing = Array.isArray(checkResult.missing_items) ? checkResult.missing_items.filter(Boolean) : [];
        return missing.length ? `待补充：${missing.join("、")}` : "尚未通过完整性检查";
      }
      const targetCheck = Array.isArray(checkResult.checks)
        ? checkResult.checks.find(item => String(item || "").includes("数量、金额或仓位"))
        : "";
      return targetCheck ? `检查通过；${targetCheck}` : "完整性检查通过";
    }

    async function refreshStockWorkflow(symbol, tab = "tasks") {
      await loadDeepStockOverview(symbol);
      activateStockSpaceTab(tab);
    }

    function showActionPlanForm(host, symbol, plan = null) {
      host.querySelector(".action-plan-form")?.remove();
      const form = document.createElement("form"); form.className = "action-plan-form";
      const actionPlanIdempotencyKey = plan ? null : positionIdempotencyKey("action-plan");
      const actionType = document.createElement("select");
      [["buy", "买入"], ["add", "增加持仓"], ["reduce", "减少持仓"], ["sell", "卖出"], ["hold", "保持观察"]].forEach(([value, label]) => { const option = document.createElement("option"); option.value = value; option.textContent = label; actionType.appendChild(option); });
      actionType.value = plan?.action_type || "buy";
      const trigger = document.createElement("textarea"); trigger.className = "form-wide"; trigger.required = true; trigger.value = plan?.trigger_text || ""; trigger.placeholder = "写下你自己的触发条件，例如：公告确认订单变化后再重新评估";
      const quantity = document.createElement("input"); quantity.inputMode = "decimal"; quantity.value = plan?.target_quantity ?? ""; quantity.placeholder = "可选，例如 500";
      const amount = document.createElement("input"); amount.inputMode = "decimal"; amount.value = plan?.target_amount ?? ""; amount.placeholder = "可选，例如 20000";
      const position = document.createElement("input"); position.inputMode = "decimal"; position.value = plan?.target_position_percent ?? ""; position.placeholder = "可选，例如 10";
      const expiresAt = document.createElement("input"); expiresAt.type = "datetime-local"; expiresAt.value = plan?.expires_at ? localDateTimeValue(new Date(plan.expires_at)) : "";
      const status = document.createElement("div"); status.className = "action-plan-form-status"; status.textContent = "系统只检查并保存你的条件，不生成建议。数量、金额和仓位都可以留空。";
      const actions = document.createElement("div"); actions.className = "action-plan-form-actions";
      const save = document.createElement("button"); save.type = "submit"; save.className = "btn primary"; save.textContent = plan ? "保存新版本" : "保存计划草稿";
      const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "btn"; cancel.textContent = "取消"; cancel.addEventListener("click", () => form.remove());
      actions.append(save, cancel);
      form.append(
        positionField("方向", actionType),
        positionField("到期时间", expiresAt),
        positionField("用户触发条件", trigger),
        positionField("目标数量", quantity),
        positionField("目标金额", amount),
        positionField("目标仓位（%）", position),
        status,
        actions
      );
      form.addEventListener("submit", async event => {
        event.preventDefault();
        if (!trigger.value.trim()) { status.textContent = "请先填写你自己的触发条件。"; trigger.focus(); return; }
        save.disabled = true; cancel.disabled = true; status.textContent = "正在保存计划…";
        const body = {
          action_type: actionType.value,
          trigger_text: trigger.value.trim(),
          target_quantity: quantity.value.trim() || null,
          target_amount: amount.value.trim() || null,
          target_position_percent: position.value.trim() || null,
          expires_at: expiresAt.value ? new Date(expiresAt.value).toISOString() : null
        };
        try {
          if (plan) {
            await api(`/v1/action-plans/${encodeURIComponent(plan.id)}`, {method: "PATCH", body: JSON.stringify({...body, base_version: plan.version})});
          } else {
            await api(`/v1/stocks/${encodeURIComponent(symbol)}/action-plans`, {
              method: "POST",
              headers: {"Idempotency-Key": actionPlanIdempotencyKey},
              body: JSON.stringify(body)
            });
          }
          await refreshStockWorkflow(symbol, "tasks");
        } catch {
          save.disabled = false; cancel.disabled = false; status.textContent = "计划尚未保存，请检查内容后再次提交。";
        }
      });
      host.appendChild(form); trigger.focus();
    }

    async function transitionActionPlan(symbol, plan, nextStatus, button) {
      const original = button.textContent; button.disabled = true;
      try {
        await api(`/v1/action-plans/${encodeURIComponent(plan.id)}/transition`, {method: "POST", body: JSON.stringify({base_version: plan.version, status: nextStatus})});
        await refreshStockWorkflow(symbol, "tasks");
      } catch {
        button.disabled = false; button.textContent = original;
      }
    }

    function renderActionPlanWorkspace(symbol, plans, positionWorkspace) {
      const section = document.createElement("section"); section.className = "action-plan-section";
      const head = document.createElement("div"); head.className = "action-plan-head";
      const copyWrap = document.createElement("div");
      const title = document.createElement("div"); title.className = "action-plan-title"; title.textContent = "我的操作计划";
      const copy = document.createElement("div"); copy.className = "action-plan-copy"; copy.textContent = "保存自己的触发条件与目标，实际操作仍需由你主动记录。";
      copyWrap.append(title, copy);
      const create = document.createElement("button"); create.type = "button"; create.className = "btn primary"; create.textContent = "新建计划"; create.addEventListener("click", () => showActionPlanForm(section, symbol));
      head.append(copyWrap, create); section.appendChild(head);
      const boundary = document.createElement("div"); boundary.className = "action-plan-boundary"; boundary.textContent = "系统只检查用户条件，不生成建议，也不会自动执行交易。"; section.appendChild(boundary);
      const grid = document.createElement("div"); grid.className = "action-plan-grid";
      if (!plans.length) {
        const empty = document.createElement("div"); empty.className = "empty"; empty.textContent = "还没有保存的操作计划。你可以记录自己的条件，之后在真实操作时关联。"; grid.appendChild(empty);
      }
      plans.forEach(plan => {
        const card = document.createElement("article"); card.className = "action-plan-card";
        const cardHead = document.createElement("div"); cardHead.className = "action-plan-card-head";
        const cardTitle = document.createElement("div"); cardTitle.className = "action-plan-card-title"; cardTitle.textContent = `${actionPlanTypeLabel(plan.action_type)} · ${actionPlanTargetText(plan)}`;
        const status = document.createElement("span"); status.className = "action-plan-status"; status.textContent = actionPlanStatusLabel(plan.status);
        cardHead.append(cardTitle, status);
        const trigger = document.createElement("div"); trigger.className = "action-plan-trigger"; trigger.textContent = plan.trigger_text || "尚未填写用户触发条件。";
        const checkText = actionPlanCheckText(plan.check_result);
        const meta = document.createElement("div"); meta.className = "action-plan-meta"; meta.textContent = [plan.expires_at ? `到期 ${readableTime(plan.expires_at)}` : "未设置到期", `版本 ${plan.version || 1}`, checkText].filter(Boolean).join(" · ");
        const actions = document.createElement("div"); actions.className = "action-plan-actions";
        const addTransition = (label, nextStatus, primary = false) => { const button = document.createElement("button"); button.type = "button"; button.className = `btn${primary ? " primary" : ""}`; button.textContent = label; button.addEventListener("click", () => { void transitionActionPlan(symbol, plan, nextStatus, button); }); actions.appendChild(button); };
        if (["draft", "checked", "saved"].includes(plan.status)) { const edit = document.createElement("button"); edit.type = "button"; edit.className = "btn"; edit.textContent = "编辑"; edit.addEventListener("click", () => showActionPlanForm(section, symbol, plan)); actions.appendChild(edit); }
        if (plan.status === "draft") addTransition("检查条件", "checked", true);
        if (plan.status === "checked") addTransition("保存计划", "saved", true);
        if (plan.status === "saved") {
          const record = document.createElement("button"); record.type = "button"; record.className = "btn primary"; record.textContent = "记录实际操作"; record.addEventListener("click", () => showPositionOperationForm(positionWorkspace, symbol, plan.id)); actions.appendChild(record);
        }
        if (["draft", "checked", "saved"].includes(plan.status)) addTransition("取消计划", "cancelled");
        card.append(cardHead, trigger, meta, actions); grid.appendChild(card);
      });
      section.appendChild(grid); return section;
    }

    function tradeReviewVersion(review) {
      return review?.current_version || review?.latest_version || review?.version_detail || review?.draft_version || review?.draft || null;
    }

    function tradeReviewStatusLabel(status) {
      return {waiting_data: "等待数据", ready: "可生成", draft: "待确认草稿", confirmed: "已确认", archived: "已归档", revised: "已修订"}[status] || "等待复盘";
    }

    function pendingReviewDraftFor(review) {
      return state.pendingReviewDrafts[String(review?.id || "")] || null;
    }

    function rememberPendingReviewDraft(candidate) {
      const reviewId = String(candidate?.payload?.review_id || "");
      if (!reviewId || candidate?.candidate_type !== "review_draft") return;
      state.pendingReviewDrafts[reviewId] = candidate;
      state.pendingReviewDraftsLoaded = true;
    }

    function forgetPendingReviewDraft(reviewId) {
      delete state.pendingReviewDrafts[String(reviewId || "")];
    }

    async function loadPendingReviewDrafts({force = false} = {}) {
      if (!force && state.pendingReviewDraftsLoaded) return true;
      if (state.pendingReviewDraftsPromise) return state.pendingReviewDraftsPromise;
      state.pendingReviewDraftsPromise = (async () => {
        try {
          const payload = await api("/v1/ai-writebacks?status=pending_confirmation&limit=300");
          const drafts = {};
          for (const candidate of (payload.items || [])) {
            const reviewId = String(candidate?.payload?.review_id || "");
            if (candidate.candidate_type === "review_draft" && reviewId) drafts[reviewId] = candidate;
          }
          state.pendingReviewDrafts = drafts;
          state.pendingReviewDraftsLoaded = true;
          return true;
        } catch {
          state.pendingReviewDraftsLoaded = false;
          return false;
        } finally {
          state.pendingReviewDraftsPromise = null;
        }
      })();
      return state.pendingReviewDraftsPromise;
    }

    function appendPendingReviewDraftCandidate(host, review, refreshCallback) {
      const candidate = pendingReviewDraftFor(review);
      if (!candidate) return false;
      appendAIWritebackCandidate(host, candidate, {
        onConfirmed: async () => {
          forgetPendingReviewDraft(review.id);
          await refreshCallback();
        },
        onRejected: async () => {
          forgetPendingReviewDraft(review.id);
          await refreshCallback();
        }
      });
      return true;
    }

    async function generateTradeReviewDraft(symbol, review, button) {
      button.disabled = true;
      try {
        const candidate = await api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/generate-draft`, {method: "POST", body: JSON.stringify({base_version: tradeReviewVersion(review)?.version_no || 0})});
        rememberPendingReviewDraft(candidate);
        const host = button.closest(".trade-review-card") || button.parentElement;
        host.querySelector(":scope > .ai-writeback-card")?.remove();
        button.hidden = true;
        appendAIWritebackCandidate(host, candidate, {
          onConfirmed: async () => { await refreshStockWorkflow(symbol, "history"); },
          onRejected: async () => { forgetPendingReviewDraft(review.id); button.hidden = false; button.disabled = false; }
        });
      } catch { button.disabled = false; button.textContent = "重新生成草稿"; }
    }

    async function archiveTradeReview(symbol, review, button) {
      button.disabled = true;
      try {
        await api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/archive`, {method: "POST", body: JSON.stringify({base_version: tradeReviewVersion(review)?.version_no || 1})});
        await refreshStockWorkflow(symbol, "history");
      } catch { button.disabled = false; }
    }

    function showTradeReviewEditor(card, symbol, review, refreshCallback = null) {
      card.querySelector(".trade-review-editor")?.remove();
      const version = tradeReviewVersion(review) || {};
      if (!review?.id) return;
      const editor = document.createElement("form"); editor.className = "trade-review-editor";
      const priceResult = document.createElement("textarea"); priceResult.className = "form-wide"; priceResult.value = friendlyStructuredText(version.price_result || review.price_result, ""); priceResult.placeholder = "价格结果：只记录可核验价格路径、费用和数据边界";
      const logicResult = document.createElement("textarea"); logicResult.className = "form-wide"; logicResult.value = friendlyStructuredText(version.logic_result || review.logic_result, ""); logicResult.placeholder = "逻辑结果：原理由哪些得到验证、哪些需要修正";
      const deviation = document.createElement("textarea"); deviation.className = "form-wide"; deviation.value = friendlyStructuredText(version.plan_deviation, ""); deviation.placeholder = "与原计划的偏离（如有）";
      const biasTags = document.createElement("input"); biasTags.value = (version.bias_tags || []).join("、"); biasTags.placeholder = "例如：追涨、提前卖出";
      const improvement = document.createElement("textarea"); improvement.className = "form-wide"; improvement.value = version.improvement_text || ""; improvement.placeholder = "下一次要改进什么；不会自动生成交易建议";
      const status = document.createElement("div"); status.className = "trade-review-editor-status"; status.textContent = "价格结果与逻辑结果必须分开；盈利不自动等于逻辑正确，亏损也不自动等于逻辑错误。";
      const actions = document.createElement("div"); actions.className = "trade-review-editor-actions";
      const save = document.createElement("button"); save.type = "button"; save.className = "btn"; save.textContent = "保存修改";
      const confirm = document.createElement("button"); confirm.type = "button"; confirm.className = "btn primary"; confirm.textContent = "保存并确认";
      const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "btn"; cancel.textContent = "取消"; cancel.addEventListener("click", () => editor.remove());
      const submitVersion = async shouldConfirm => {
        save.disabled = true; confirm.disabled = true; cancel.disabled = true; status.textContent = shouldConfirm ? "正在保存并确认复盘…" : "正在保存复盘修改…";
        try {
          const updated = await api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/draft`, {
            method: "PATCH",
            body: JSON.stringify({
              base_version: version?.version_no || 1,
              price_result: priceResult.value.trim(),
              logic_result: logicResult.value.trim(),
              plan_deviation: deviation.value.trim() || null,
              bias_tags: biasTags.value.split(/[、,，]/).map(value => value.trim()).filter(Boolean),
              improvement_text: improvement.value.trim() || null
            })
          });
          const nextVersion = updated?.current_version || updated?.draft || updated?.version || updated?.item || updated || {};
          if (shouldConfirm) {
            await api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/confirm`, {method: "POST", body: JSON.stringify({base_version: nextVersion.version_no ?? version?.version_no ?? 1})});
          }
          if (refreshCallback) await refreshCallback();
          else await refreshStockWorkflow(symbol, "history");
        } catch {
          save.disabled = false; confirm.disabled = false; cancel.disabled = false; status.textContent = "复盘尚未保存，请检查内容后再次提交。";
        }
      };
      save.addEventListener("click", () => { void submitVersion(false); });
      confirm.addEventListener("click", () => { void submitVersion(true); });
      actions.append(save, confirm, cancel);
      editor.append(positionField("价格结果", priceResult), positionField("逻辑结果", logicResult), positionField("计划偏离", deviation), positionField("偏差标签", biasTags), positionField("改进记录", improvement), status, actions);
      card.appendChild(editor); priceResult.focus();
    }

    async function generateTradeReviewCenterDraft(review, button) {
      button.disabled = true;
      button.textContent = "AI 正在复盘…";
      try {
        const candidate = await api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/generate-draft`, {method: "POST", body: JSON.stringify({base_version: tradeReviewVersion(review)?.version_no || 0})});
        rememberPendingReviewDraft(candidate);
        button.hidden = true;
        $("tradeReviewDetail").querySelector(":scope > .ai-writeback-card")?.remove();
        appendAIWritebackCandidate($("tradeReviewDetail"), candidate, {
          onConfirmed: async () => { await loadTradeReviewCenter(review.id); void loadTodayOverview(); },
          onRejected: async () => { forgetPendingReviewDraft(review.id); button.hidden = false; button.disabled = false; button.textContent = "生成 AI 逻辑草稿"; }
        });
      } catch (error) {
        button.disabled = false;
        button.textContent = "重新生成草稿";
        openReader("交易复盘暂未生成", error?.message || "已记录的操作和价格结果仍然保留，请稍后重试。", "真实操作数据不会被覆盖");
      }
    }

    async function archiveTradeReviewCenter(review, button) {
      button.disabled = true;
      try {
        await api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/archive`, {method: "POST", body: JSON.stringify({base_version: tradeReviewVersion(review)?.version_no || 1})});
        await loadTradeReviewCenter(review.id);
        void loadTodayOverview();
      } catch { button.disabled = false; }
    }

    function appendTradeReviewMetric(container, label, value) {
      const card = document.createElement("div"); card.className = "review-detail-metric";
      const labelNode = document.createElement("span"); labelNode.textContent = label;
      const valueNode = document.createElement("strong"); valueNode.textContent = value || "—";
      card.append(labelNode, valueNode); container.appendChild(card);
    }

    function appendTradeReviewSection(container, titleText, copyText, metaText = "") {
      const section = document.createElement("section"); section.className = "review-detail-section";
      const title = document.createElement("div"); title.className = "review-detail-section-title";
      title.append(document.createTextNode(titleText));
      if (metaText) title.appendChild(Object.assign(document.createElement("small"), {textContent: metaText}));
      const copy = document.createElement("div"); copy.className = "trade-center-detail-copy"; copy.textContent = copyText || "当前没有可展示内容。";
      section.append(title, copy); container.appendChild(section);
    }

    function appendTradeReviewFollowup(container, review, refreshCallback = null) {
      const version = tradeReviewVersion(review) || {};
      const improvement = String(version.improvement_text || "").trim();
      if (!improvement || !["confirmed", "archived"].includes(review.status)) return;
      const followups = review.followups || {};
      const section = document.createElement("section"); section.className = "review-followup";
      const title = document.createElement("div"); title.className = "review-followup-title"; title.textContent = "把复盘改进变成下一步";
      const copy = document.createElement("div"); copy.className = "review-followup-copy"; copy.textContent = improvement;
      const actions = document.createElement("div"); actions.className = "review-followup-actions";
      const status = document.createElement("div"); status.className = "review-followup-status";

      const refresh = async () => {
        if (refreshCallback) await refreshCallback();
        else if (review.symbol && $("deepStockSymbol")?.value === review.symbol) await refreshStockWorkflow(review.symbol, "history");
      };
      const taskButton = document.createElement("button"); taskButton.type = "button"; taskButton.className = "btn primary";
      taskButton.textContent = followups.observation_task ? "已保存为观察任务" : "保存为观察任务";
      taskButton.disabled = Boolean(followups.observation_task);
      taskButton.addEventListener("click", async () => {
        taskButton.disabled = true; status.textContent = "正在保存这条已确认的复盘改进…";
        try {
          const result = await api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/followups`, {method: "POST", body: JSON.stringify({target: "observation_task", priority: "normal"})});
          taskButton.textContent = "已保存为观察任务";
          status.textContent = `已进入“任务与操作”：${result.observation_task?.title || "复盘改进"}`;
          await refresh();
        } catch (error) {
          taskButton.disabled = false; status.textContent = error.message || "复盘改进暂未保存，请稍后重试。";
        }
      });
      actions.appendChild(taskButton);

      const renderThesisState = thesis => {
        section.querySelector(".review-followup-draft")?.remove();
        actions.querySelectorAll("[data-review-thesis-action]").forEach(node => node.remove());
        if (!thesis) return;
        const draft = document.createElement("div"); draft.className = "review-followup-draft"; draft.textContent = thesis.reason_text || "已生成判断草稿。";
        section.insertBefore(draft, actions);
        if (thesis.status === "active") {
          status.textContent = "这条复盘改进已经写入当前正式判断。";
          return;
        }
        const confirm = document.createElement("button"); confirm.type = "button"; confirm.className = "btn primary"; confirm.dataset.reviewThesisAction = "confirm"; confirm.textContent = "确认更新当前判断";
        const reject = document.createElement("button"); reject.type = "button"; reject.className = "btn"; reject.dataset.reviewThesisAction = "reject"; reject.textContent = "放弃这份草稿";
        confirm.addEventListener("click", async () => {
          confirm.disabled = true; reject.disabled = true; status.textContent = "正在写入版本化当前判断…";
          try {
            await api(`/v1/stocks/${encodeURIComponent(review.symbol)}/theses/${encodeURIComponent(thesis.id)}/confirm`, {method: "POST"});
            status.textContent = "已由你确认并写入当前判断；原判断版本仍保留。";
            await loadWatchlist(); await refresh();
          } catch (error) {
            confirm.disabled = false; reject.disabled = false; status.textContent = error.message || "判断草稿暂未确认，请刷新后重试。";
          }
        });
        reject.addEventListener("click", async () => {
          confirm.disabled = true; reject.disabled = true; status.textContent = "正在保留原判断…";
          try {
            await api(`/v1/stocks/${encodeURIComponent(review.symbol)}/theses/${encodeURIComponent(thesis.id)}/reject`, {method: "POST"});
            status.textContent = "已放弃草稿，当前正式判断没有变化。"; draft.remove(); confirm.remove(); reject.remove();
            await refresh();
          } catch (error) {
            confirm.disabled = false; reject.disabled = false; status.textContent = error.message || "草稿暂未处理，请稍后重试。";
          }
        });
        actions.append(confirm, reject);
      };

      const thesisButton = document.createElement("button"); thesisButton.type = "button"; thesisButton.className = "btn"; thesisButton.dataset.reviewThesisAction = "create";
      thesisButton.textContent = followups.thesis ? (followups.thesis.status === "active" ? "已写入当前判断" : "查看判断草稿") : "形成判断草稿";
      thesisButton.disabled = followups.thesis?.status === "active";
      thesisButton.addEventListener("click", async () => {
        if (followups.thesis) { renderThesisState(followups.thesis); return; }
        thesisButton.disabled = true; status.textContent = "正在保留原判断并追加这条复盘改进…";
        try {
          const result = await api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/followups`, {method: "POST", body: JSON.stringify({target: "thesis_draft", priority: "normal"})});
          thesisButton.remove(); renderThesisState(result.thesis);
          status.textContent = result.status === "already_applied" ? "这条改进已经在当前判断中。" : "草稿已生成；再次确认前不会改变正式判断。";
        } catch (error) {
          thesisButton.disabled = false; status.textContent = error.message || "判断草稿暂未生成，请稍后重试。";
        }
      });
      actions.appendChild(thesisButton);
      section.append(title, copy, actions, status); container.appendChild(section);
      if (followups.observation_task) status.textContent = `已保存观察任务：${followups.observation_task.title || "复盘改进"}`;
      if (followups.thesis) renderThesisState(followups.thesis);
    }

    function renderTradeReviewCenterDetail(review, packet = null) {
      const container = $("tradeReviewDetail"); container.innerHTML = "";
      if (!review) {
        container.innerHTML = '<div class="review-detail-empty"><div class="review-detail-empty-icon">◇</div><strong>选择一条真实操作</strong><span>价格结果、操作时上下文和逻辑复盘会分开显示。</span></div>';
        return;
      }
      const operation = review.operation || {};
      const plan = review.action_plan || {};
      const observation = review.price_observation || {};
      const version = tradeReviewVersion(review) || {};
      const head = document.createElement("div"); head.className = "review-detail-head";
      const identity = document.createElement("div");
      const title = document.createElement("div"); title.className = "review-detail-title"; title.textContent = `${review.name || review.symbol} · ${actionPlanTypeLabel(operation.operation_type)}复盘`;
      const subtitle = document.createElement("div"); subtitle.className = "review-detail-subtitle"; subtitle.textContent = `${review.symbol} · ${readableTime(operation.operated_at || review.created_at)} · ${review.horizon_sessions || 3} 个后续交易日`;
      identity.append(title, subtitle);
      const badge = document.createElement("span"); badge.className = `review-status ${review.status}`; badge.textContent = tradeReviewStatusLabel(review.status);
      head.append(identity, badge); container.appendChild(head);

      const metrics = document.createElement("div"); metrics.className = "review-detail-metrics";
      appendTradeReviewMetric(metrics, "操作方向", actionPlanTypeLabel(operation.operation_type));
      appendTradeReviewMetric(metrics, "操作价格", operation.price ? numeric(operation.price) : "—");
      appendTradeReviewMetric(metrics, "操作数量", operation.quantity ? numeric(operation.quantity) : "—");
      appendTradeReviewMetric(metrics, "价格变化", observation.price_change_pct == null ? "等待数据" : pct(observation.price_change_pct));
      container.appendChild(metrics);

      appendTradeReviewSection(container, "确定性价格结果", observation.summary || version.price_result || "后续交易日数据仍在积累。", observation.end_date ? `数据截至 ${observation.end_date}` : "来自已落库日线");
      appendTradeReviewSection(container, "操作时记录", operation.reason_text || "没有填写操作理由。", plan.id ? "已关联用户操作计划" : "未关联操作计划");
      if (plan.trigger_text) appendTradeReviewSection(container, "原操作计划", plan.trigger_text, actionPlanTargetText(plan));
      if (version.logic_result) appendTradeReviewSection(container, "逻辑复盘", version.logic_result, `版本 ${version.version_no || 1} · ${version.created_source === "ai" ? "AI草稿" : "用户版本"}`);
      if (version.plan_deviation) appendTradeReviewSection(container, "计划偏离", version.plan_deviation);
      if (version.improvement_text) appendTradeReviewSection(container, "下一次改进", version.improvement_text);
      if (version.bias_tags?.length) {
        const tags = document.createElement("div"); tags.className = "trade-center-tags";
        version.bias_tags.forEach(value => { const tag = document.createElement("span"); tag.className = "trade-center-tag"; tag.textContent = value; tags.appendChild(tag); });
        container.appendChild(tags);
      }
      appendTradeReviewFollowup(container, review, async () => { await loadTradeReviewCenter(review.id); void loadTodayOverview(); });

      const actions = document.createElement("div"); actions.className = "trade-center-actions";
      const pendingCandidate = pendingReviewDraftFor(review);
      if (review.status === "ready" && !pendingCandidate && state.pendingReviewDraftsLoaded) {
        const generate = document.createElement("button"); generate.type = "button"; generate.className = "btn primary"; generate.textContent = "生成 AI 逻辑草稿"; generate.addEventListener("click", () => { void generateTradeReviewCenterDraft(review, generate); }); actions.appendChild(generate);
      }
      if (review.status === "ready" && !pendingCandidate && !state.pendingReviewDraftsLoaded) {
        const waiting = document.createElement("button"); waiting.type = "button"; waiting.className = "btn"; waiting.disabled = true; waiting.textContent = "正在核对已有草稿…"; actions.appendChild(waiting);
      }
      if (["draft", "revised"].includes(review.status)) {
        const edit = document.createElement("button"); edit.type = "button"; edit.className = "btn primary"; edit.textContent = "编辑并确认"; edit.addEventListener("click", () => showTradeReviewEditor(container, review.symbol, review, async () => { await loadTradeReviewCenter(review.id); void loadTodayOverview(); })); actions.appendChild(edit);
      }
      if (review.status === "confirmed") {
        const archive = document.createElement("button"); archive.type = "button"; archive.className = "btn"; archive.textContent = "归档复盘"; archive.addEventListener("click", () => { void archiveTradeReviewCenter(review, archive); }); actions.appendChild(archive);
      }
      const stock = document.createElement("button"); stock.type = "button"; stock.className = "btn"; stock.textContent = "进入股票研究空间"; stock.addEventListener("click", () => { void openDeepStockSymbol(review.symbol); }); actions.appendChild(stock);
      container.appendChild(actions);
      const boundary = document.createElement("div"); boundary.className = "review-outcome-boundary"; boundary.textContent = packet?.boundary || "价格结果与逻辑结果分开；盈利不自动等于逻辑正确，亏损也不自动等于逻辑错误。"; container.appendChild(boundary);
      if (pendingCandidate) appendPendingReviewDraftCandidate(container, review, async () => { await loadTradeReviewCenter(review.id); void loadTodayOverview(); });
    }

    function openTradeReviewCenterItem(reviewId) {
      state.selectedTradeReviewId = reviewId;
      document.querySelectorAll("#tradeReviewList .review-run-item").forEach(item => item.classList.toggle("active", item.dataset.reviewId === reviewId));
      renderTradeReviewCenterDetail(state.tradeReviewCenter.find(item => item.id === reviewId), {boundary: state.tradeReviewCenterBoundary});
      if (state.workspacePage === "review" && state.reviewTab === "trades") syncWorkspaceUrl("replace");
    }

    function renderTradeReviewCenter(data, preferredId = null) {
      state.tradeReviewCenter = data.items || [];
      state.tradeReviewCenterSummary = data.summary || {};
      state.tradeReviewCenterBoundary = data.boundary || "";
      const summary = state.tradeReviewCenterSummary;
      $("tradeReviewSummary").textContent = `显示 ${summary.filtered || 0} / ${summary.total || 0} 条 · ${summary.actionable || 0} 条待处理`;
      const container = $("tradeReviewList"); container.innerHTML = "";
      for (const review of state.tradeReviewCenter) {
        const operation = review.operation || {};
        const observation = review.price_observation || {};
        const row = document.createElement("button"); row.type = "button"; row.className = "review-run-item"; row.dataset.reviewId = review.id;
        const head = document.createElement("div"); head.className = "review-run-item-head";
        const title = document.createElement("div"); title.className = "review-run-item-title"; title.textContent = `${review.name || review.symbol} · ${actionPlanTypeLabel(operation.operation_type)}`;
        const badge = document.createElement("span"); badge.className = `review-status ${review.status}`; badge.textContent = tradeReviewStatusLabel(review.status);
        head.append(title, badge);
        const detail = document.createElement("div"); detail.className = "review-run-item-question"; detail.textContent = operation.reason_text || review.action_plan?.trigger_text || "已保存真实操作，等待复盘。";
        const price = document.createElement("div"); price.className = "trade-center-item-price"; price.textContent = observation.ready ? `T+${review.horizon_sessions || 3} · ${observation.price_change_pct == null ? "价格结果已就绪" : pct(observation.price_change_pct)}` : `后续数据 ${observation.available_sessions || 0}/${observation.required_sessions || review.horizon_sessions || 3}`;
        const meta = document.createElement("div"); meta.className = "review-run-item-meta"; meta.textContent = [readableTime(operation.operated_at || review.created_at), review.action_plan ? "已关联计划" : "未关联计划"].join(" · ");
        row.append(head, detail, price, meta); row.addEventListener("click", () => openTradeReviewCenterItem(review.id)); container.appendChild(row);
      }
      if (!container.children.length) {
        container.innerHTML = '<div class="empty">当前筛选条件下没有交易复盘。真实操作完成后会自动进入这里。</div>';
        renderTradeReviewCenterDetail(null);
        return;
      }
      const nextId = preferredId && state.tradeReviewCenter.some(item => item.id === preferredId)
        ? preferredId
        : state.selectedTradeReviewId && state.tradeReviewCenter.some(item => item.id === state.selectedTradeReviewId)
          ? state.selectedTradeReviewId
          : state.tradeReviewCenter[0].id;
      openTradeReviewCenterItem(nextId);
    }

    async function loadTradeReviewCenter(preferredId = null) {
      const params = new URLSearchParams({limit: "100"});
      const status = $("tradeReviewStatus").value;
      const query = $("tradeReviewSearch").value.trim();
      if (status) params.set("status", status);
      if (query) params.set("q", query);
      const [data] = await Promise.all([
        api(`/v1/trade-reviews?${params.toString()}`),
        loadPendingReviewDrafts()
      ]);
      renderTradeReviewCenter(data, preferredId || state.pendingTradeReviewId);
      state.pendingTradeReviewId = null;
      return data;
    }

    function renderTradeReviewWorkspace(symbol, reviews) {
      const section = document.createElement("section"); section.className = "trade-review-section";
      const head = document.createElement("div"); head.className = "trade-review-head";
      const copyWrap = document.createElement("div");
      const title = document.createElement("div"); title.className = "trade-review-title"; title.textContent = "真实交易复盘";
      const copy = document.createElement("div"); copy.className = "trade-review-copy"; copy.textContent = "真实操作完成后，复盘按等待数据、可生成、AI草稿、已确认顺序推进。";
      copyWrap.append(title, copy); head.appendChild(copyWrap); section.appendChild(head);
      const boundary = document.createElement("div"); boundary.className = "trade-review-boundary"; boundary.textContent = "价格结果和逻辑结果分开呈现；数据不完整时不会给出伪精确净收益。"; section.appendChild(boundary);
      const grid = document.createElement("div"); grid.className = "trade-review-grid";
      if (!reviews.length) {
        const empty = document.createElement("div"); empty.className = "empty"; empty.textContent = "完成并保存真实操作后，这里会形成复盘记录。"; grid.appendChild(empty);
      }
      reviews.forEach(review => {
        const version = tradeReviewVersion(review) || {};
        const reviewStatus = review.status || version.status;
        const pendingCandidate = pendingReviewDraftFor(review);
        const card = document.createElement("article"); card.className = "trade-review-card";
        const cardHead = document.createElement("div"); cardHead.className = "trade-review-card-head";
        const titleNode = document.createElement("div"); titleNode.className = "trade-review-card-title"; titleNode.textContent = review.title || `${actionPlanTypeLabel(review.operation?.operation_type || review.operation_type)}复盘`;
        const status = document.createElement("span"); status.className = "trade-review-status"; status.textContent = tradeReviewStatusLabel(reviewStatus);
        cardHead.append(titleNode, status);
        const meta = document.createElement("div"); meta.className = "trade-review-meta"; meta.textContent = [review.operated_at || review.operation?.operated_at ? readableTime(review.operated_at || review.operation.operated_at) : "", review.plan_id || review.action_plan_id ? "已关联操作计划" : "未关联操作计划", version.version_no ? `版本 ${version.version_no}` : "", version.created_source ? `来源 ${version.created_source === "ai" ? "AI草稿" : "用户"}` : ""].filter(Boolean).join(" · ");
        const columns = document.createElement("div"); columns.className = "trade-review-columns";
        [["价格结果", version.price_result || review.price_result], ["逻辑结果", version.logic_result || review.logic_result]].forEach(([label, value]) => { const column = document.createElement("div"); column.className = "trade-review-column"; const labelNode = document.createElement("span"); labelNode.textContent = label; const valueNode = document.createElement("strong"); valueNode.textContent = friendlyStructuredText(value); column.append(labelNode, valueNode); columns.appendChild(column); });
        const result = document.createElement("div"); result.className = "trade-review-result"; result.textContent = [version.plan_deviation ? `计划偏离：${friendlyStructuredText(version.plan_deviation)}` : "", version.bias_tags?.length ? `偏差标签：${version.bias_tags.join("、")}` : "", version.improvement_text ? `改进：${version.improvement_text}` : ""].filter(Boolean).join("\n");
        const actions = document.createElement("div"); actions.className = "trade-review-actions";
        if (reviewStatus === "ready" && !pendingCandidate && state.pendingReviewDraftsLoaded) { const generate = document.createElement("button"); generate.type = "button"; generate.className = "btn primary"; generate.textContent = "立即生成草稿"; generate.addEventListener("click", () => { void generateTradeReviewDraft(symbol, review, generate); }); actions.appendChild(generate); }
        if (reviewStatus === "ready" && !pendingCandidate && !state.pendingReviewDraftsLoaded) { const waiting = document.createElement("button"); waiting.type = "button"; waiting.className = "btn"; waiting.disabled = true; waiting.textContent = "正在核对已有草稿…"; actions.appendChild(waiting); }
        if (["draft", "revised"].includes(reviewStatus)) { const edit = document.createElement("button"); edit.type = "button"; edit.className = "btn primary"; edit.textContent = "编辑并确认"; edit.addEventListener("click", () => showTradeReviewEditor(card, symbol, review)); actions.appendChild(edit); }
        if (reviewStatus === "confirmed") { const archive = document.createElement("button"); archive.type = "button"; archive.className = "btn"; archive.textContent = "归档"; archive.addEventListener("click", () => { void archiveTradeReview(symbol, review, archive); }); actions.appendChild(archive); }
        card.append(cardHead, meta, columns); if (result.textContent) card.appendChild(result); card.appendChild(actions);
        appendTradeReviewFollowup(card, review, async () => { await refreshStockWorkflow(symbol, "history"); });
        if (pendingCandidate) appendPendingReviewDraftCandidate(card, review, async () => { await refreshStockWorkflow(symbol, "history"); });
        grid.appendChild(card);
      });
      section.appendChild(grid); return section;
    }
