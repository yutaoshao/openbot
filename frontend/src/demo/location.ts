/** The preview is a separate route so transport isolation precedes React effects. */
export function isDesktopDemoPath(pathname: string): boolean {
  let decoded = pathname;
  try { decoded = decodeURIComponent(pathname); } catch { /* Match malformed paths literally. */ }
  return decoded === "/desktop-demo" || decoded.startsWith("/desktop-demo/");
}

/** Keep the explicit first-run import scenario while navigating the preview. */
export function demoLinkPath(path: string): string {
  return new URLSearchParams(window.location.search).get("preview") === "import" ? `${path}?preview=import` : path;
}
