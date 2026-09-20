import type { CatalogItem, Color, GameMode } from "./types.ts";

export const CATEGORY_LABELS: Readonly<Record<string, string>> = {
  random: "ランダム",
  rule_based: "ルールベース",
  machine_learning: "機械学習",
  reinforcement_learning: "強化学習",
  neural_network: "ニューラルネットワーク",
  generative_ai: "生成 AI",
};

export type CatalogGroup = {
  category: string;
  label: string;
  items: CatalogItem[];
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category;
}

export function groupCatalog(items: readonly CatalogItem[]): CatalogGroup[] {
  const groups: CatalogGroup[] = [];
  const index = new Map<string, number>();
  for (const item of items) {
    const existing = index.get(item.category);
    if (existing === undefined) {
      index.set(item.category, groups.length);
      groups.push({
        category: item.category,
        label: categoryLabel(item.category),
        items: [item],
      });
    } else {
      groups[existing].items.push(item);
    }
  }
  return groups;
}

export function displayNameOf(
  items: readonly CatalogItem[],
  specimenId: string,
): string {
  return (
    items.find((item) => item.specimen_id === specimenId)?.display_name ??
    specimenId
  );
}

export function matchSummary(input: {
  mode: GameMode;
  humanColor: Color;
  opponentId: string;
  blackId: string;
  whiteId: string;
  items: readonly CatalogItem[];
}): string {
  if (input.mode === "human_vs_agent") {
    const color = input.humanColor === "black" ? "黒" : "白";
    const opponent = displayNameOf(input.items, input.opponentId);
    return `あなた・${color} vs ${opponent}`;
  }
  const black = displayNameOf(input.items, input.blackId);
  const white = displayNameOf(input.items, input.whiteId);
  return `${black} vs ${white}`;
}

export function selectedSpecimenIds(input: {
  mode: GameMode;
  opponentId: string;
  blackId: string;
  whiteId: string;
}): readonly string[] {
  if (input.mode === "human_vs_agent") {
    return input.opponentId === "" ? [] : [input.opponentId];
  }
  return [input.blackId, input.whiteId].filter((id) => id !== "");
}
