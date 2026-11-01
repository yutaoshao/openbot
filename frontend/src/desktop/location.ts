import { demoLinkPath } from "../demo/location";

export type DesktopBasePath = "/desktop" | "/desktop-demo";

/** Preserve the application namespace and the Demo's explicit import scenario. */
export function desktopLinkPath(basePath: DesktopBasePath, path = ""): string {
  const destination = `${basePath}${path}`;
  return basePath === "/desktop-demo" ? demoLinkPath(destination) : destination;
}

export function isDesktopPath(pathname: string): boolean {
  let path = pathname;
  try { path = decodeURIComponent(pathname); } catch { /* The router handles invalid URLs. */ }
  return path === "/desktop" || path.startsWith("/desktop/");
}
