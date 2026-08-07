import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AdvisorCitation } from "../adapters";
import { EvidenceDrawer } from "./EvidenceDrawer";

const citations: AdvisorCitation[] = Array.from({ length: 12 }, (_, index) => ({
  id: `citation-${index + 1}`,
  sourceName: `来源 ${index + 1}`,
  sourceUrl: null,
  evidenceType: index === 0 ? "company_business_composition" : "structured_data",
  dataTime: "2026-08-06",
  reportPeriod: "2026-03-31",
  excerpt: `证据摘要 ${index + 1}`,
  limitations: ["需要结合原文核验。"],
}));

describe("EvidenceDrawer", () => {
  it("keeps a long evidence list compact until the user expands it", () => {
    render(<EvidenceDrawer citations={citations} sources={[]} />);

    expect(screen.getAllByRole("article")).toHaveLength(10);
    fireEvent.click(screen.getByRole("button", { name: "查看全部 12 条" }));
    expect(screen.getAllByRole("article")).toHaveLength(12);
    fireEvent.click(screen.getByRole("button", { name: "收起" }));
    expect(screen.getAllByRole("article")).toHaveLength(10);
  });
});
