/** The preview is a separate route so transport isolation precedes React effects. */
export function isDesktopDemoPath(pathname: string): boolean {
  let decoded = pathname;
  try { decoded = decodeURIComponent(pathname); } catch { /* Match malformed paths literally. */ }
  return decoded === "/desktop-demo" || decoded.startsWith("/desktop-demo/");
}
