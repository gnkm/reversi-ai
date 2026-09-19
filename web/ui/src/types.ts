export type Color = "black" | "white";
export type Cell = "empty" | "black" | "white";
export type GameMode = "human_vs_agent" | "agent_vs_agent";

export type CatalogItem = {
  specimen_id: string;
  category: string;
  display_name: string;
  description: string;
};

export type HumanPlayer = {
  kind: "human";
};

export type SpecimenPlayer = {
  kind: "specimen";
  specimen_id: string;
};

export type PlayerSpec = HumanPlayer | SpecimenPlayer;

export type CreateGameRequest = {
  black: PlayerSpec;
  white: PlayerSpec;
};

export type PlaceMove = {
  type: "place";
  square: string;
};

export type PassMove = {
  type: "pass";
};

export type Move = PlaceMove | PassMove;

export type OfficialScore = {
  black: number;
  white: number;
};

export type GameResult = {
  winner: "black" | "white" | "draw";
  black: "win" | "loss" | "draw";
  white: "win" | "loss" | "draw";
};

export type GameState = {
  id: string;
  board: Cell[][];
  side_to_move: Color;
  legal_moves: string[];
  pass_is_legal: boolean;
  last_move: Move | null;
  is_over: boolean;
  official_score: OfficialScore;
  result: GameResult | null;
  status: "in_progress" | "completed" | "unplayable";
  continuation_possible: boolean;
  unplayable_reason: "external_model_failed" | null;
  black: PlayerSpec;
  white: PlayerSpec;
};
