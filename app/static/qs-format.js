function pct(value) {
      if (value === null || value === undefined) return "—";
      const number = Number(value);
      return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
    }

    function numeric(value) {
      if (value === null || value === undefined) return "—";
      return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
    }

    function compactNumber(value, currency = "") {
      const number = Number(value);
      if (!Number.isFinite(number)) return "—";
      const absolute = Math.abs(number);
      const suffix = currency ? ` ${currency}` : "";
      if (absolute >= 1e12) return `${(number / 1e12).toFixed(2)}万亿${suffix}`;
      if (absolute >= 1e8) return `${(number / 1e8).toFixed(2)}亿${suffix}`;
      if (absolute >= 1e4) return `${(number / 1e4).toFixed(2)}万${suffix}`;
      return `${numeric(number)}${suffix}`;
    }

    function splitAnswerFootnotes(text) {
      const value = String(text || "");
      const marker = /^###\s+成分行情口径补充\s*$/m;
      const match = marker.exec(value);
      if (!match || match.index <= 0) return {main: value, footnotes: ""};
      return {
        main: value.slice(0, match.index).trim(),
        footnotes: value.slice(match.index + match[0].length).trim()
      };
    }

    function appendAnswerFootnotes(node, text) {
      if (!text) return;
      const details = document.createElement("details");
      details.className = "answer-footnotes";
      const summary = document.createElement("summary");
      summary.textContent = "数据口径";
      const body = document.createElement("div");
      body.className = "answer-footnotes-body";
      body.appendChild(renderMarkdown(text));
      details.append(summary, body);
      node.appendChild(details);
    }

    function renderFinalAnswerBody(node, text) {
      const sections = splitAnswerFootnotes(text);
      const body = document.createElement("div");
      body.className = "message-body";
      body.appendChild(renderMarkdown(sections.main));
      node.appendChild(body);
      appendAnswerFootnotes(node, sections.footnotes);
    }
