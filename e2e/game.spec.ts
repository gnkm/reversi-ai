import { expect, test } from "@playwright/test";

const OPENING_LEGAL = ["c4", "d3", "e6", "f5"] as const;

test("手番表示と合法手の印が観測できる", async ({ page }, testInfo) => {
  expect(testInfo.project.use.channel).toBe("chrome");
  await page.goto("/");
  const start = page.getByRole("button", { name: "対局を開始" });
  await expect(start).toBeEnabled();
  await start.click();

  await expect(page.getByRole("heading", { name: "盤面" })).toBeVisible();
  await expect(
    page.getByText("手番は黒です。あなたの入力待ちです。"),
  ).toBeVisible();
  await expect(page.getByLabel("リバーシ盤")).toBeVisible();

  for (const square of OPENING_LEGAL) {
    await expect(
      page.getByRole("button", { name: new RegExp(`${square} .*合法手`) }),
    ).toBeVisible();
    await expect(
      page.locator(`[data-square="${square}"] .legal-mark`),
    ).toBeVisible();
  }
  await expect(page.locator('[data-square="a1"] .legal-mark')).toHaveCount(0);
  await expect(page.locator('[data-square="d4"] .legal-mark')).toHaveCount(0);
});
