import { describe, expect, it } from "vitest";
import {
  categoryLabel,
  displayNameOf,
  groupCatalog,
  matchSummary,
  selectedSpecimenIds,
} from "./catalog.ts";
import type { CatalogItem } from "./types.ts";

const ITEMS: CatalogItem[] = [
  {
    specimen_id: "random_uniform",
    category: "random",
    display_name: "ランダム (一様)",
    description: "合法手を等確率で選ぶ。",
  },
  {
    specimen_id: "most_flips",
    category: "rule_based",
    display_name: "ルールベース (最多取り)",
    description: "最多取り。",
  },
  {
    specimen_id: "minimax",
    category: "rule_based",
    display_name: "ルールベース (ミニマックス)",
    description: "ミニマックス。",
  },
];

describe("categoryLabel", () => {
  it("既知のカテゴリは日本語にする", () => {
    expect(categoryLabel("rule_based")).toBe("ルールベース");
    expect(categoryLabel("generative_ai")).toBe("生成 AI");
  });

  it("未知のカテゴリはそのまま返す", () => {
    expect(categoryLabel("unknown")).toBe("unknown");
  });
});

describe("groupCatalog", () => {
  it("出現順を保ち同一カテゴリをまとめる", () => {
    const groups = groupCatalog(ITEMS);
    expect(groups.map((group) => group.label)).toEqual([
      "ランダム",
      "ルールベース",
    ]);
    expect(groups[1]?.items.map((item) => item.specimen_id)).toEqual([
      "most_flips",
      "minimax",
    ]);
  });
});

describe("matchSummary", () => {
  it("利用者対エージェントの要約を作る", () => {
    expect(
      matchSummary({
        mode: "human_vs_agent",
        humanColor: "black",
        opponentId: "minimax",
        blackId: "",
        whiteId: "",
        items: ITEMS,
      }),
    ).toBe("あなた・黒 vs ルールベース (ミニマックス)");
  });

  it("エージェント対エージェントの要約を作る", () => {
    expect(
      matchSummary({
        mode: "agent_vs_agent",
        humanColor: "black",
        opponentId: "",
        blackId: "minimax",
        whiteId: "random_uniform",
        items: ITEMS,
      }),
    ).toBe("ルールベース (ミニマックス) vs ランダム (一様)");
  });
});

describe("selectedSpecimenIds", () => {
  it("利用者対エージェントでは対戦相手だけを選中にする", () => {
    expect(
      selectedSpecimenIds({
        mode: "human_vs_agent",
        opponentId: "most_flips",
        blackId: "minimax",
        whiteId: "random_uniform",
      }),
    ).toEqual(["most_flips"]);
  });
});

describe("displayNameOf", () => {
  it("未登録の個体 ID はそのまま返す", () => {
    expect(displayNameOf(ITEMS, "missing")).toBe("missing");
  });
});
