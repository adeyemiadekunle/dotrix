import { expect, test, type Page } from "@playwright/test";

import { createTask, signUpWithProject } from "./helpers";

// A real workspace's board: what a person does there is saved by the API, so each test reloads
// the page to see it again.

const column = (page: Page, name: string) => page.getByRole("region", { name, exact: true });

test("create a task, move it to In Progress, and comment on it", async ({ page }) => {
  const { key } = await signUpWithProject(page);

  await page.getByRole("toolbar").getByRole("button", { name: "New task" }).click();
  const form = page.getByRole("dialog", { name: "New task" });
  await form.getByRole("textbox", { name: "Task name" }).fill("Write the onboarding docs");
  await form.getByRole("button", { name: "Create task" }).click();
  await expect(form).toBeHidden();

  // It starts in To Do, with the project's next key.
  const card = column(page, "To Do").getByRole("button", { name: "Write the onboarding docs" });
  await expect(card).toContainText(`${key}-1`);
  await card.click();

  const drawer = page.getByRole("dialog", { name: "Task: Write the onboarding docs" });
  await drawer.getByRole("button", { name: /^Status/ }).click();
  await page.getByRole("menuitemradio", { name: /In Progress/ }).click();
  await expect(drawer.getByRole("button", { name: "Status: In Progress" })).toBeVisible();

  await drawer.getByRole("textbox", { name: "Comment" }).fill("Starting with the CLI guide.");
  await drawer.getByRole("button", { name: "Comment", exact: true }).click();
  await expect(drawer.getByText("Starting with the CLI guide.")).toBeVisible();
  await drawer.getByRole("button", { name: "Close" }).click();
  await expect(drawer).toBeHidden();
  await expect(column(page, "In Progress").getByText("Write the onboarding docs")).toBeVisible();

  // Saved, not only on this screen.
  await page.reload();
  await expect(column(page, "In Progress").getByText("Write the onboarding docs")).toBeVisible();
  await column(page, "In Progress").getByRole("button", { name: "Write the onboarding docs" }).click();
  await expect(page.getByRole("dialog").getByText("Starting with the CLI guide.")).toBeVisible();
});

test("a column's + starts the task in that column, and search narrows the board", async ({ page }) => {
  // An empty board has no columns yet, so there's a task to begin with.
  const { workspace, project } = await signUpWithProject(page);
  await createTask(page, workspace.id, project.id, { title: "Draft the pricing page" });
  await page.reload();

  await page.getByRole("button", { name: "Add task to Blocked" }).click();
  const name = page.getByRole("textbox", { name: "New task name" });
  await name.fill("Waiting on the pricing rules");
  await name.press("Enter");
  await expect(column(page, "Blocked").getByRole("button", { name: "Waiting on the pricing rules" })).toBeVisible();

  await page.reload();
  await expect(column(page, "Blocked").getByRole("button", { name: "Waiting on the pricing rules" })).toBeVisible();

  const search = page.getByRole("textbox", { name: "Search tasks" });
  await search.fill("nothing matches this");
  await expect(page.getByText("Waiting on the pricing rules")).toHaveCount(0);
  await search.fill("pricing");
  await expect(column(page, "Blocked").getByText("Waiting on the pricing rules")).toBeVisible();
});

test("marking a card complete moves it to Done, and List shows the same tasks", async ({ page }) => {
  const { workspace, project, key } = await signUpWithProject(page);
  await createTask(page, workspace.id, project.id, { title: "Draft the pricing page" });
  await createTask(page, workspace.id, project.id, { title: "Check the invoices" });
  await page.reload();

  const card = column(page, "To Do").getByRole("button", { name: "Draft the pricing page" });
  await card.hover();
  await card.getByRole("button", { name: "Mark complete" }).click();
  await expect(column(page, "Done").getByText("Draft the pricing page")).toBeVisible();
  await expect(column(page, "To Do").getByText("Check the invoices")).toBeVisible();

  await page.getByRole("navigation", { name: "Project views" }).getByRole("button", { name: "List", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/p/${key}/list`));
  await expect(page.getByText("Draft the pricing page", { exact: true })).toBeVisible();
  await expect(page.getByText("Check the invoices", { exact: true })).toBeVisible();

  await page.reload();
  await page.getByRole("navigation", { name: "Project views" }).getByRole("button", { name: "Board", exact: true }).click();
  await expect(column(page, "Done").getByText("Draft the pricing page")).toBeVisible();
});

test("the project's views open from its tabs: Overview, Knowledge and Activity", async ({ page }) => {
  const { key } = await signUpWithProject(page);
  const views = page.getByRole("navigation", { name: "Project views" });

  await views.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/p/${key}/overview`));
  await expect(page.getByRole("heading", { name: "Kumove", level: 1 })).toBeVisible();

  await views.getByRole("button", { name: "Knowledge", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/p/${key}/knowledge`));
  await expect(page.getByText("vision.md").first()).toBeVisible();

  await views.getByRole("button", { name: "Activity", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/p/${key}/activity`));
  await expect(page.getByText(/No activity yet|created Kumove/).first()).toBeVisible();
});
