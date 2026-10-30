export function isDesktopPath(pathname: string): boolean {
  let path = pathname;
  try { path = decodeURIComponent(pathname); } catch { /* The router handles invalid URLs. */ }
  return path === "/desktop" || path.startsWith("/desktop/");
}
