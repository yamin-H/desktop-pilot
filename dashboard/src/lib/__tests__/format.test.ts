import { describe, expect, it } from "vitest";
import { ageText, safeHref, signClass, withThousands } from "../format";

describe("withThousands", () => {
  it("adds separators without touching digits", () => {
    expect(withThousands("60393.93")).toBe("60,393.93");
    expect(withThousands("1000")).toBe("1,000");
    expect(withThousands("-1234567.5")).toBe("-1,234,567.5");
    expect(withThousands("0.3495")).toBe("0.3495");
    expect(withThousands("999")).toBe("999");
    expect(withThousands("12345678901234567890.123456789")).toBe("12,345,678,901,234,567,890.123456789");
  });
  it("shows a dash for unknown values and leaves other text alone", () => {
    expect(withThousands(null)).toBe("—");
    expect(withThousands(undefined)).toBe("—");
    expect(withThousands("abc")).toBe("abc");
  });
});

describe("signClass", () => {
  it("tells gains, losses, zero and unknown apart", () => {
    expect(signClass("12.5")).toBe("gain");
    expect(signClass("-0.01")).toBe("loss");
    expect(signClass("0")).toBe("flat");
    expect(signClass("0.00")).toBe("flat");
    expect(signClass(null)).toBe("unknown");
  });
});

describe("ageText", () => {
  it("writes short ages", () => {
    expect(ageText(3)).toBe("3s");
    expect(ageText(125)).toBe("2m 5s");
    expect(ageText(3 * 3600 + 120)).toBe("3h 2m");
  });
});

describe("safeHref", () => {
  it("allows only http and https links", () => {
    expect(safeHref("https://x.test/a?b=1")).toBe("https://x.test/a?b=1");
    expect(safeHref(" http://x.test ")).toBe("http://x.test");
    expect(safeHref("javascript:alert(1)")).toBe("#");
    expect(safeHref("//evil.example")).toBe("#");
    expect(safeHref("data:text/html,hi")).toBe("#");
    expect(safeHref("")).toBe("#");
  });
});