import { describe, expect, it } from "vitest";
import { formatDotenv, parseDotenv } from "./dotenv";

describe("parseDotenv", () => {
  it("reads KEY=value lines, skipping blanks and comments", () => {
    expect(parseDotenv('# settings\nLOG_LEVEL=debug\n\nexport NODE_ENV = test\nGREETING="hello world"\nEMPTY=\n')).toEqual({
      variables: { LOG_LEVEL: "debug", NODE_ENV: "test", GREETING: "hello world", EMPTY: "" },
    });
  });

  it("keeps = inside values", () => {
    expect(parseDotenv("QUERY=a=b").variables).toEqual({ QUERY: "a=b" });
  });

  it("names the line it can't read, and a name set twice", () => {
    expect(parseDotenv("OK=1\nnot a variable").error).toBe("Line 2 isn't KEY=value");
    expect(parseDotenv("=x").error).toBe("Line 1 isn't KEY=value");
    expect(parseDotenv("A=1\nA=2").error).toBe("A is set twice");
  });

  it("formats back to one line each", () => {
    expect(formatDotenv({ A: "1", B: "two words" })).toBe("A=1\nB=two words");
  });
});
