import { z } from "zod";

export const GAME_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export const SQUARE_PATTERN = /^[a-h][1-8]$/;

export const colorSchema = z.enum(["black", "white"]);
export const cellSchema = z.enum(["empty", "black", "white"]);
export const categorySchema = z.enum([
  "random",
  "rule_based",
  "machine_learning",
  "reinforcement_learning",
  "neural_network",
  "generative_ai",
]);
export const errorCodeSchema = z.enum([
  "validation_error",
  "game_not_found",
  "specimen_not_found",
  "illegal_move",
  "game_already_over",
  "external_model_failed",
  "internal_error",
]);
export const outcomeSchema = z.enum(["win", "loss", "draw"]);
export const gameStatusSchema = z.enum([
  "in_progress",
  "completed",
  "unplayable",
]);
export const winnerSchema = z.enum(["black", "white", "draw"]);
export const unplayableReasonSchema = z.literal("external_model_failed");

export const problemSchema = z.strictObject({
  type: z.string(),
  title: z.string(),
  status: z.number().int(),
  detail: z.string(),
  code: errorCodeSchema,
});

export const catalogItemSchema = z.strictObject({
  specimen_id: z.string().min(1),
  category: categorySchema,
  display_name: z.string().min(1),
  description: z.string(),
});

export const catalogSchema = z.strictObject({
  items: z.array(catalogItemSchema),
});

export const humanPlayerSchema = z.strictObject({
  kind: z.literal("human"),
});

export const specimenPlayerSchema = z.strictObject({
  kind: z.literal("specimen"),
  specimen_id: z.string().min(1),
});

export const playerSpecSchema = z.discriminatedUnion("kind", [
  humanPlayerSchema,
  specimenPlayerSchema,
]);

export const createGameRequestSchema = z.strictObject({
  black: playerSpecSchema,
  white: playerSpecSchema,
});

export const placeMoveSchema = z.strictObject({
  type: z.literal("place"),
  square: z.string().regex(SQUARE_PATTERN),
});

export const passMoveSchema = z.strictObject({
  type: z.literal("pass"),
});

export const moveSchema = z.discriminatedUnion("type", [
  placeMoveSchema,
  passMoveSchema,
]);

export const officialScoreSchema = z.strictObject({
  black: z.number().int().min(0).max(64),
  white: z.number().int().min(0).max(64),
});

export const gameResultSchema = z.strictObject({
  winner: winnerSchema,
  black: outcomeSchema,
  white: outcomeSchema,
});

const boardRowSchema = z.array(cellSchema).length(8);

export const gameStateSchema = z.strictObject({
  id: z.string().regex(GAME_ID_PATTERN),
  board: z.array(boardRowSchema).length(8),
  side_to_move: colorSchema,
  legal_moves: z.array(z.string().regex(SQUARE_PATTERN)),
  pass_is_legal: z.boolean(),
  last_move: moveSchema.nullable(),
  is_over: z.boolean(),
  official_score: officialScoreSchema,
  result: gameResultSchema.nullable(),
  status: gameStatusSchema,
  continuation_possible: z.boolean(),
  unplayable_reason: unplayableReasonSchema.nullable(),
  black: playerSpecSchema,
  white: playerSpecSchema,
});

export const moveAppliedSchema = z.strictObject({
  applied: z.literal(true),
  game: gameStateSchema,
});

export const illegalMoveNotAppliedSchema = z.strictObject({
  applied: z.literal(false),
  code: z.literal("illegal_move"),
  detail: z.string(),
  game: gameStateSchema,
});

export const gameUnplayableSchema = z.strictObject({
  applied: z.literal(false),
  code: z.literal("external_model_failed"),
  detail: z.string(),
  continuation_possible: z.literal(false),
  game: gameStateSchema,
});

export const decideRequestSchema = z.strictObject({
  specimen_id: z.string().min(1),
  game: gameStateSchema,
});

export const snapshotEventSchema = z.strictObject({
  type: z.literal("snapshot"),
  game: gameStateSchema,
});

export const moveAppliedEventSchema = z.strictObject({
  type: z.literal("move_applied"),
  move: moveSchema,
  game: gameStateSchema,
});

export const moveRejectedEventSchema = z.strictObject({
  type: z.literal("move_rejected"),
  move: moveSchema,
  game: gameStateSchema,
});

export const gameOverEventSchema = z.strictObject({
  type: z.literal("game_over"),
  game: gameStateSchema,
});

export const unplayableEventSchema = z.strictObject({
  type: z.literal("unplayable"),
  reason: unplayableReasonSchema,
  game: gameStateSchema,
});

export const gameEventSchema = z.discriminatedUnion("type", [
  snapshotEventSchema,
  moveAppliedEventSchema,
  moveRejectedEventSchema,
  gameOverEventSchema,
  unplayableEventSchema,
]);

export type ErrorCode = z.infer<typeof errorCodeSchema>;
export type Catalog = z.infer<typeof catalogSchema>;
export type CreateGameRequest = z.infer<typeof createGameRequestSchema>;
export type Move = z.infer<typeof moveSchema>;
export type GameState = z.infer<typeof gameStateSchema>;
export type IllegalMoveNotApplied = z.infer<typeof illegalMoveNotAppliedSchema>;
export type GameEvent = z.infer<typeof gameEventSchema>;
