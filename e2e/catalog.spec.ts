import { expect, test } from "@playwright/test";

const CATALOG_NAMES = [
  "ランダム (一様)",
  "ルールベース (最多取り)",
  "ルールベース (位置評価)",
  "ルールベース (ミニマックス)",
  "ルールベース (定石)",
  "機械学習 (棋譜)",
  "機械学習 (LightGBM)",
  "強化学習 (自己対局)",
  "ニューラルネットワーク (棋譜)",
  "生成 AI (Jev)",
] as const;

test("カタログ一覧（日本語）から盤面へ移れる", async ({ page }, testInfo) => {
  expect(testInfo.project.name).toBe("chrome");
  expect(testInfo.project.use.channel).toBe("chrome");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "カタログ" })).toBeVisible();
  await expect(page.getByText("利用者対エージェント")).toBeVisible();
  for (const name of CATALOG_NAMES) {
    await expect(page.getByRole("heading", { name })).toBeVisible();
  }
  await expect(
    page.getByText(/自分の手番の合法手を等確率で 1 つ選ぶ/),
  ).toBeVisible();

  const start = page.getByRole("button", { name: "対局を開始" });
  await expect(start).toBeEnabled();
  await start.click();

  await expect(page.getByRole("heading", { name: "盤面" })).toBeVisible();
  await expect(page).toHaveURL(/\/game$/);
  await expect(page.getByRole("heading", { name: "カタログ" })).toHaveCount(0);
  await expect(page.getByLabel("対戦相手")).toHaveCount(0);
});
