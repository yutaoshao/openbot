const FRAGMENT_KEY = "openbot-desktop-token";
let exchange: { origin: string; token: string; promise: Promise<void> } | null = null;
let error: string | null = null;
const listeners = new Set<() => void>();

function setError(value: string | null): void {
  error = value;
  listeners.forEach((listener) => listener());
}
export const browserSessionError = (): string | null => error;
export function subscribeBrowserSession(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
export function hasBrowserSessionFragment(): boolean {
  return new URLSearchParams(window.location.hash.slice(1)).has(FRAGMENT_KEY);
}

/** Verify the native fragment once; the bearer stays in this page's memory. */
export async function ensureBrowserSession(): Promise<void> {
  const location = window.location;
  const fragments = new URLSearchParams(location.hash.slice(1));
  const token = fragments.get(FRAGMENT_KEY);
  if (fragments.has(FRAGMENT_KEY)) {
    fragments.delete(FRAGMENT_KEY);
    const rest = fragments.toString();
    window.history.replaceState(null, "", `${location.pathname}${location.search}${rest ? `#${rest}` : ""}`);
    setError(null);
    const origin = location.origin;
    exchange = { origin, token: token ?? "", promise: (async () => {
      if (location.protocol !== "http:" || location.hostname !== "127.0.0.1" || !token) throw new Error("desktopLive.browserSessionError");
      const response = await fetch(`${origin}/api/desktop/browser-session`, {
        method: "POST", credentials: "omit", signal: AbortSignal.timeout(15_000),
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: "{}",
      });
      if (!response.ok) throw new Error("desktopLive.browserSessionError");
    })().catch(() => { setError("desktopLive.browserSessionError"); throw new Error("desktopLive.browserSessionError"); }) };
  }
  if (exchange?.origin === location.origin) {
    await exchange.promise;
  }
  if (error) throw new Error(error);
}

export function browserSessionBearer(): string | undefined {
  return !error && exchange?.origin === window.location.origin ? exchange.token : undefined;
}

export function expireBrowserSession(desktopService = false): void {
  if (desktopService || exchange?.origin === window.location.origin) setError("desktopLive.browserSessionError");
}
