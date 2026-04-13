import { expect, test } from "@playwright/test";

test("home page visible", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("WriterAgent")).toBeVisible();
});
