import { describe, expect, it } from "vitest";
import { backendUrl } from "../proxy";

const BASE = "http://127.0.0.1:8000";

describe("backendUrl", () => {
  it("builds the backend address and keeps the query", () => {
    expect(backendUrl(BASE, ["pnl"], "")?.toString()).toBe("http://127.0.0.1:8000/api/pnl");
    expect(backendUrl(BASE + "/", ["trades"], "?limit=5")?.toString()).toBe("http://127.0.0.1:8000/api/trades?limit=5");
  });
  it("refuses anything that is not a plain word", () => {
    for (const bad of [[], [""], [".."], ["."], ["a", ".."], ["a/b"], ["a\\b"], ["%2e%2e"], ["a b"], ["a?b"], ["a#b"], ["http:"]]) {
      expect(backendUrl(BASE, bad, "")).toBeNull();
    }
  });
  it("always stays on the configured backend", () => {
    expect(backendUrl(BASE, ["market"], "?x=//evil.example")?.host).toBe("127.0.0.1:8000");
  });
});