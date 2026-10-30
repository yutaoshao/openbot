import { isDesktopDemoPath } from "../demo/location";
import { isDesktopPath } from "../desktop/location";

/** Preserve the active application boundary when shared pages link to each other. */
export function pagePath(path: string): string {
  const base = isDesktopDemoPath(window.location.pathname) ? "/desktop-demo"
    : isDesktopPath(window.location.pathname) ? "/desktop" : null;
  if (!base) return path;
  if (path === "/chat") return base;
  return `${base}/manage/${path === "/" ? "overview" : path.slice(1)}`;
}
