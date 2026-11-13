import { expect, test, type Page } from "@playwright/test";

async function showMarkdown(page: Page, markdown: string) {
  await page.goto("/w/dotrix/p/WEB/knowledge");
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByLabel("Document", { exact: true }).fill(markdown);
  await page.getByRole("button", { name: "Save", exact: true }).click();
}

test("inline Astryx code escapes markup and follows light/dark typography", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await showMarkdown(page, 'Use `const html = "<b>literal</b>"` for this example.');
  const code = page.locator(".knowledge-documents code.astryx-code");
  await expect(code).toHaveText('const html = "<b>literal</b>"');
  await expect(code.locator("b")).toHaveCount(0);
  await expect(code).toHaveCSS("font-family", /Geist Mono/);
  await expect(code).toHaveCSS("color", "rgb(21, 17, 12)");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(code).toHaveCSS("color", "rgb(223, 226, 229)");
});

test("fenced code copies exact text and handles unknown/unlabelled languages without page overflow", async ({ page, context, baseURL }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: baseURL! });
  const code = 'const html = "<b>literal</b>";\n\tconsole.log(html);';
  const unknown = 'unrecognized <language> & "literal"';
  const long = "long_" + "x".repeat(700);
  await showMarkdown(page, `\`\`\`javascript\n${code}\n\`\`\`\n\n\`\`\`unknown-dotrix-language\n${unknown}\n\`\`\`\n\n\`\`\`\n${long}\n\`\`\``);
  const blocks = page.locator(".knowledge-documents .astryx-code-block");
  await expect(blocks).toHaveCount(3);
  await expect(blocks.nth(0).getByText("javascript", { exact: true })).toBeVisible();
  await expect(blocks.nth(0).locator("code")).toHaveText(code);
  await expect(blocks.nth(1).locator("code")).toHaveText(unknown);
  await expect(blocks.nth(2).locator("code")).toHaveText(long);
  await blocks.nth(0).getByRole("button", { name: "Copy code", exact: true }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(code);
  await blocks.nth(1).getByRole("button", { name: "Copy code", exact: true }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(unknown);
  const lightBackground = await blocks.nth(0).evaluate((el) => getComputedStyle(el).backgroundColor);
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(blocks.nth(0)).not.toHaveCSS("background-color", lightBackground);
  await expect(blocks.nth(0).locator("code")).toHaveText(code);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});
