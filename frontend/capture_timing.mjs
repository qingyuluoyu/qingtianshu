import fs from "fs";
import { execSync } from "child_process";

const timingData = [];
const baseUrl = "http://localhost:8000";
const cookieFile = "C:/Users/dazhu/AppData/Local/Temp/qingshu_session.txt";

// Read cookie
const cookieContent = fs.readFileSync(cookieFile, "utf8");
const cookieMatch = cookieContent.match(/qingshu_session\t([^\t\n]+)/);
const sessionCookie = cookieMatch ? cookieMatch[1] : "";

const endpoints = [
  { name: "overview", path: "/v1/today/overview" },
  { name: "indices", path: "/indices?scope=all&group=china" },
  { name: "breadth", path: "/markets/breadth" },
  { name: "sectors", path: "/sectors/hot?limit=10" },
  { name: "watchlist", path: "/me/watchlist/brief" },
  { name: "research_actions", path: "/me/research-actions" },
  { name: "research_changes", path: "/me/research-changes?limit=20" },
  { name: "data_health", path: "/system/data-health" },
  { name: "index_history_000001", path: "/indices/000001.SS/history?range=1mo" },
  { name: "research_reports", path: "/research-reports/latest?limit=20" },
  { name: "capital_flow", path: "/markets/capital-flow" },
  { name: "positions", path: "/v1/positions" },
  { name: "global_indices", path: "/indices?scope=all&group=us" },
  { name: "live_markets", path: "/markets/live" },
  { name: "anomalies", path: "/markets/anomalies?limit=10" },
];

async function captureTiming() {

  for (const endpoint of endpoints) {
    const url = `${baseUrl}${endpoint.path}`;
    const startTime = Date.now();

    try {
      const output = execSync(
        `curl -s -b "${cookieFile}" -w "\\n%{time_namelookup}\\t%{time_connect}\\t%{time_appconnect}\\t%{time_pretransfer}\\t%{time_redirect}\\t%{time_starttransfer}\\t%{time_total}\\t%{size_download}" -o /dev/null "${url}" 2>&0`
      ).toString();

      const lines = output.trim().split("\n");
      const timingLine = lines[lines.length - 1];
      const [
        ,
        namelookup,
        connect,
        appconnect,
        pretransfer,
        redirect,
        starttransfer,
        total,
        size,
      ] = timingLine.split("\t");

      const timing = {
        name: endpoint.name,
        path: endpoint.path,
        namelookup: parseFloat(namelookup || 0),
        connect: parseFloat(connect || 0),
        appconnect: parseFloat(appconnect || 0),
        pretransfer: parseFloat(pretransfer || 0),
        redirect: parseFloat(redirect || 0),
        starttransfer: parseFloat(starttransfer || 0),
        total: parseFloat(total || 0),
        size: parseInt(size || 0),
      };

      timingData.push(timing);
      console.log(`${endpoint.name}: ${timing.total.toFixed(3)}s`);
    } catch (e) {
      console.log(`${endpoint.name}: FAILED - ${e.message}`);
    }
  }

  // Save as JSON
  fs.writeFileSync(
    "C:/Users/dazhu/AppData/Local/Temp/api_timing.json",
    JSON.stringify(timingData, null, 2)
  );
  console.log("\nTiming data saved to api_timing.json");

  // Print summary
  console.log("\n=== TIMING SUMMARY ===");
  timingData.forEach((t) => {
    console.log(
      `${t.name.padEnd(20)} ${t.total.toFixed(3).padStart(8)}s  (TTFB: ${t.starttransfer.toFixed(3)}s)`
    );
  });
}

captureTiming().catch(console.error);
