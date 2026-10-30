import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";

import { isDesktopDemoPath } from "../demo/location";
import { useI18n } from "../i18n";
import { browserSessionError, ensureBrowserSession, hasBrowserSessionFragment, subscribeBrowserSession } from "./browser-session";
import { isDesktopPath } from "./location";

export function BrowserSessionGate({ children }: { children: ReactNode }): JSX.Element {
  const { t } = useI18n();
  const localUi = isDesktopDemoPath(window.location.pathname) || isDesktopPath(window.location.pathname);
  const [pending, setPending] = useState(() => !localUi && hasBrowserSessionFragment());
  const error = useSyncExternalStore(subscribeBrowserSession, browserSessionError);
  useEffect(() => {
    if (!pending) return;
    void ensureBrowserSession().then(() => setPending(false)).catch(() => setPending(false));
  }, [pending]);
  if (!localUi && error) return <main className="detail-empty" role="alert">{t(error)}</main>;
  if (pending) return <main className="detail-empty" role="status">{t("common.loading")}</main>;
  return <>{children}</>;
}
