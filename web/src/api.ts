export type Json = Record<string, any>;
let csrf = "";
let establishing: Promise<void> | null = null;
export async function establish() {
  if (!establishing)
    establishing = fetch("/api/session", { credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok)
          throw new Error("Unable to establish a local session");
        csrf = (await response.json()).csrf;
      })
      .finally(() => {
        establishing = null;
      });
  return establishing;
}
export async function api<T = Json>(
  path: string,
  body?: unknown,
  method = body === undefined ? "GET" : "POST",
  signal?: AbortSignal,
): Promise<T> {
  if (!csrf) await establish();
  const response = await fetch("/api" + path, {
    method,
    credentials: "same-origin",
    signal,
    headers: { "Content-Type": "application/json", "X-GoX-CSRF": csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "Operation failed; check current state before retrying",
    );
  return result as T;
}
export const money = (value: number | undefined | null) =>
  value == null
    ? "--"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
      }).format(value);
export const price = (value: number | undefined | null) =>
  value == null
    ? "--"
    : new Intl.NumberFormat("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(value);
export const ct = (value: string | undefined | null) =>
  value
    ? new Intl.DateTimeFormat("en-US", {
        timeZone: "America/Chicago",
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(new Date(value)) + " CT"
    : "Unavailable";
export const age = (value: string | undefined) =>
  value ? Math.max(0, (Date.now() - Date.parse(value)) / 1000) : Infinity;
