import { describe, expect, it } from "vitest";

import { modelName } from "@/lib/agent";

describe("modelName", () => {
  it("shortens models the way people say them", () => {
    expect(modelName("anthropic:claude-opus-5-5")).toBe("Opus 5.5");
    expect(modelName("claude-haiku-5-5")).toBe("Haiku 5.5");
    expect(modelName("anthropic:claude-sonnet-4-5-20250929")).toBe("Sonnet 4.5");
    expect(modelName("anthropic:claude-opus-4")).toBe("Opus 4");
    expect(modelName("openai:gpt-5.5")).toBe("GPT-5.5");
    expect(modelName("openai:gpt-5.4-mini")).toBe("GPT-5.4 mini");
    expect(modelName("google_genai:gemini-3.8-flash")).toBe("Gemini 3.8 Flash");
  });
  it("keeps anything else as its id, without the provider", () => {
    expect(modelName("openrouter:meta-llama/llama-4")).toBe("meta-llama/llama-4");
    expect(modelName(null)).toBe("");
    expect(modelName("openai:test", "OpenAI test")).toBe("OpenAI test");
    expect(modelName("anthropic:claude-opus-5-5", "Claude Opus 5.5 (long)")).toBe("Opus 5.5");
  });
});
