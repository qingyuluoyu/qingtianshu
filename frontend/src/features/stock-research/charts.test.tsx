import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CandlePoint } from "./adapters";
import { CandlestickChart } from "./charts";

function candles(count = 30): CandlePoint[] {
  return Array.from({ length: count }, (_, index) => {
    const close = 30 + index * 0.2 + (index % 3) * 0.05;
    return {
      timestamp: `2026-07-${String(index + 1).padStart(2, "0")}T07:00:00+08:00`,
      open: close - 0.12,
      high: close + 0.3,
      low: close - 0.35,
      close,
      adjustedClose: close,
      volume: 1_000_000 + index * 10_000,
    };
  });
}

describe("CandlestickChart", () => {
  it("renders deterministic moving averages only when enough real closes exist", () => {
    const { container, rerender } = render(<CandlestickChart points={candles(30)} />);
    expect(container.querySelector('[data-series="ma5"]')).toBeInTheDocument();
    expect(container.querySelector('[data-series="ma10"]')).toBeInTheDocument();
    expect(container.querySelector('[data-series="ma20"]')).toBeInTheDocument();

    rerender(<CandlestickChart points={candles(12)} />);
    expect(container.querySelector('[data-series="ma5"]')).toBeInTheDocument();
    expect(container.querySelector('[data-series="ma10"]')).toBeInTheDocument();
    expect(container.querySelector('[data-series="ma20"]')).not.toBeInTheDocument();
  });

  it("zooms the visible real-candle window and resets without synthesizing points", () => {
    render(<CandlestickChart points={candles(30)} />);
    const chart = screen.getByRole("img", { name: /日 K 蜡烛与成交量图/ });
    expect(chart).toHaveAttribute("data-visible-count", "30");
    fireEvent.wheel(chart, { deltaY: -100 });
    expect(Number(chart.getAttribute("data-visible-count"))).toBeLessThan(30);
    fireEvent.doubleClick(chart);
    expect(chart).toHaveAttribute("data-visible-count", "30");
  });

  it("supports keyboard crosshair inspection", () => {
    render(<CandlestickChart points={candles(30)} />);
    const chart = screen.getByRole("img", { name: /日 K 蜡烛与成交量图/ });
    chart.focus();
    fireEvent.keyDown(chart, { key: "ArrowLeft" });
    expect(screen.getByTestId("kline-crosshair")).toBeInTheDocument();
    expect(chart).toHaveAttribute("aria-keyshortcuts", "ArrowLeft ArrowRight + - 0");
  });
});
