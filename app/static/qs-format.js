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
