const KEY = "openbot_desktop_unconfirmed_v1";

export type PendingRequest = { request_id: string; instance_id: string };

export function readPendingRequest(): PendingRequest | null {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(KEY) || "null");
    if (typeof value !== "object" || value === null) return null;
    const record = value as Record<string, unknown>;
    if (typeof record.request_id !== "string" || typeof record.instance_id !== "string") return null;
    return { request_id: record.request_id, instance_id: record.instance_id };
  } catch { return null; }
}

export function samePendingRequest(left: PendingRequest | null, right: PendingRequest): boolean {
  return left !== null && left.request_id === right.request_id && left.instance_id === right.instance_id;
}

export function rememberPendingRequest(owner: PendingRequest): void {
  sessionStorage.setItem(KEY, JSON.stringify({ request_id: owner.request_id, instance_id: owner.instance_id }));
}

/** A late operation may only remove the exact record it owns. */
export function forgetPendingRequest(owner: PendingRequest): void {
  if (samePendingRequest(readPendingRequest(), owner)) sessionStorage.removeItem(KEY);
}
