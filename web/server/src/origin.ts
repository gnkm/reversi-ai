const STATE_CHANGING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export function isStateChangingMethod(method: string): boolean {
  return STATE_CHANGING.has(method.toUpperCase());
}

export function originMatches(
  originHeader: string | undefined,
  publicOrigin: string,
): boolean {
  return originHeader === publicOrigin;
}
