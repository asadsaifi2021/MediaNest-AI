import { describe, expect, it } from "vitest";
import { validatePublicConfig } from "../../src/config";
import { parseEmbedding } from "../../src/api";

describe("browser configuration", () => {
  it("blocks server secrets and legacy keys before creating an auth client", () => {
    expect(
      validatePublicConfig("https://example.supabase.co", "sb_secret_private"),
    ).toContain("publishable");
    expect(
      validatePublicConfig("https://example.supabase.co", "eyJlegacy"),
    ).toContain("publishable");
    expect(
      validatePublicConfig(
        "https://example.supabase.co",
        "sb_publishable_example",
      ),
    ).toBeNull();
  });
  it("requires secure remote auth and complete configuration", () => {
    expect(
      validatePublicConfig("http://example.com", "sb_publishable_example"),
    ).toContain("HTTPS");
    expect(
      validatePublicConfig("http://localhost:54321", "sb_publishable_example"),
    ).toBeNull();
    expect(validatePublicConfig("", "")).toBeTruthy();
    expect(validatePublicConfig("broken", "sb_publishable_example")).toContain(
      "invalid",
    );
  });
});
describe("face vector validation", () => {
  it("accepts only finite numeric vectors of the expected size", () => {
    expect(parseEmbedding(JSON.stringify(Array(512).fill(0.1)))).toHaveLength(
      512,
    );
    expect(() => parseEmbedding(JSON.stringify(Array(511).fill(0.1)))).toThrow(
      "512",
    );
    expect(() =>
      parseEmbedding(JSON.stringify(Array(512).fill("0.1"))),
    ).toThrow("finite");
    expect(() => parseEmbedding(JSON.stringify(Array(512).fill(0)))).toThrow(
      "zero",
    );
    expect(() => parseEmbedding('{"bad": true}')).toThrow();
  });
});
