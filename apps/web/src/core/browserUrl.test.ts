import { describe, expect, it } from "vitest";

import { hostOf, toAddress } from "./browserUrl";

describe("toAddress", () => {
  it("opens a dev server on plain http", () => {
    expect(toAddress("localhost:3000")).toBe("http://localhost:3000/");
    expect(toAddress(" 127.0.0.1:5173/app?x=1 ")).toBe("http://127.0.0.1:5173/app?x=1");
    expect(toAddress("app.localhost:8080")).toBe("http://app.localhost:8080/");
    expect(toAddress("devbox:3000")).toBe("http://devbox:3000/");
    expect(toAddress("[::1]:3000")).toBe("http://[::1]:3000/");
  });

  it("opens a site on https", () => {
    expect(toAddress("example.com")).toBe("https://example.com/");
    expect(toAddress("docs.example.com/a#b")).toBe("https://docs.example.com/a#b");
    expect(toAddress("example.com:8443")).toBe("https://example.com:8443/");
  });

  it("keeps a web address as typed", () => {
    expect(toAddress("http://example.com/x")).toBe("http://example.com/x");
    expect(toAddress("https://example.com")).toBe("https://example.com/");
  });

  it("refuses what isn't a web address", () => {
    for (const text of ["", "   ", "file:///etc/passwd", "javascript://x", "chrome://settings", "two words", "justaword"]) expect(toAddress(text)).toBeNull();
  });
});

describe("hostOf", () => {
  it("names a page by its host", () => {
    expect(hostOf("http://localhost:3000/a")).toBe("localhost:3000");
    expect(hostOf("nonsense")).toBe("nonsense");
  });
});
