import type { ErrorCode } from "./schemas.ts";

export function problemResponse(
  status: number,
  code: ErrorCode,
  title: string,
  detail: string,
): Response {
  return new Response(
    JSON.stringify({
      type: `urn:reversi-ai:error:${code}`,
      title,
      status,
      detail,
      code,
    }),
    {
      status,
      headers: { "content-type": "application/problem+json" },
    },
  );
}

export function validationError(): Response {
  return problemResponse(
    400,
    "validation_error",
    "Bad Request",
    "リクエストの形が契約と違う",
  );
}

export function strategyUnreachable(method: string): Response {
  if (method.toUpperCase() === "POST") {
    return problemResponse(
      422,
      "external_model_failed",
      "Unprocessable Entity",
      "戦略プロセスを呼び出せず、対局を継続できない",
    );
  }
  return problemResponse(
    500,
    "internal_error",
    "Internal Server Error",
    "戦略プロセスを呼び出せない",
  );
}
