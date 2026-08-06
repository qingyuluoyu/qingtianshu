import { describe, expect, it } from "vitest";
import {
  parseBreadth,
  parseOverview,
  parseDataHealth,
  parseIndices,
  parseSectors,
} from "./adapters";
import fs from "fs";
import path from "path";

const responsesDir = "C:/Users/dazhu/AppData/Local/Temp/api_responses";

describe("real API response adapter verification", () => {
  it("parses real overview response", () => {
    const data = JSON.parse(fs.readFileSync(path.join(responsesDir, "01_overview.json"), "utf8"));
    const result = parseOverview(data);
    // Overview type doesn't expose contract_version; check generatedAt instead
    expect(result.generatedAt).toBeTruthy();
    expect(result.headline).toBeTruthy();
    console.log("   overview generatedAt:", result.generatedAt);
    console.log("   overview headline:", result.headline.slice(0, 60) + "...");
  });

  it("parses real indices response", () => {
    const data = JSON.parse(fs.readFileSync(path.join(responsesDir, "02_indices.json"), "utf8"));
    const result = parseIndices(data);
    // Indices type has 'items' not 'indices'
    expect(result.items.length).toBeGreaterThan(0);
    console.log("   indices count:", result.items.length);
    console.log("   indices symbols:", result.items.map((i) => i.symbol).join(", "));
  });

  it("parses real breadth response - CRITICAL TURNOVER FIELDS TEST", () => {
    const data = JSON.parse(fs.readFileSync(path.join(responsesDir, "03_breadth.json"), "utf8"));

    console.log("\n=== RAW BACKEND RESPONSE STRUCTURE ===");
    console.log("Has 'turnover' at root:", "turnover" in data);
    console.log("Has 'turnover_history' at root:", "turnover_history" in data);
    console.log("Has 'history_comparison' at root:", "history_comparison" in data);
    console.log(
      "Has 'history_comparison' inside turnover:",
      "history_comparison" in (data as any).turnover,
    );

    if ((data as any).turnover) {
      console.log("\nturnover keys:", Object.keys((data as any).turnover));
      console.log("turnover.status:", (data as any).turnover.status);
      console.log("turnover.total_amount_100m_cny:", (data as any).turnover.total_amount_100m_cny);
    }

    if ((data as any).history_comparison) {
      console.log("\nhistory_comparison keys:", Object.keys((data as any).history_comparison));
      console.log("history_comparison.status:", (data as any).history_comparison.status);
      console.log(
        "history_comparison.change_vs_previous_pct:",
        (data as any).history_comparison.change_vs_previous_pct,
      );
    }

    const result = parseBreadth(data);

    console.log("\n=== ADAPTER PARSED RESULT ===");
    console.log("status:", result.status);
    console.log("state:", result.state);
    console.log("turnoverStatus:", result.turnoverStatus);
    console.log("turnover100mCny:", result.turnover100mCny);
    console.log("historyStatus:", result.historyStatus);
    console.log("turnoverChangeVsPreviousPct:", result.turnoverChangeVsPreviousPct);
    console.log("turnoverHistory length:", result.turnoverHistory?.length ?? 0);
    console.log("turnoverHistory:", JSON.stringify(result.turnoverHistory));

    // These should pass
    expect(result.turnoverStatus).toBe("available");
    expect(result.turnover100mCny).toBeGreaterThan(0);
    expect(result.historyStatus).toBeDefined();
    expect(result.historyStatus).not.toBeNull();
    expect(result.turnoverChangeVsPreviousPct).toBeDefined();
    expect(result.turnoverChangeVsPreviousPct).not.toBeNull();

    // This will FAIL - proving the bug
    expect(result.turnoverHistory?.length).toBeGreaterThan(0);
  });

  it("parses real data health response", () => {
    const data = JSON.parse(fs.readFileSync(path.join(responsesDir, "08_data_health.json"), "utf8"));
    const result = parseDataHealth(data);
    expect(result.status).toBe("degraded");
    expect(result.createdAt).toBeTruthy();
    console.log("   dataHealth status:", result.status);
    console.log("   dataHealth createdAt:", result.createdAt);
  });

  it("parses real sectors response", () => {
    const data = JSON.parse(fs.readFileSync(path.join(responsesDir, "04_sectors.json"), "utf8"));
    const result = parseSectors(data);
    expect(result.items.length).toBeGreaterThan(0);
    console.log("   sectors count:", result.items.length);
  });
});
