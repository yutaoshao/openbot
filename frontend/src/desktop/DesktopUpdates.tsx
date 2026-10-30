import { useMutation } from "@tanstack/react-query";
import { useI18n } from "../i18n";
import { isDesktopDemoPath } from "../demo/location";
import { desktopInvoke } from "./native";

type UpdateSnapshot = { status: "unconfigured" | "current" | "available"; version?: string; notes?: string };

export function DesktopUpdates({ busy }: { busy: boolean }) {
  const { t } = useI18n();
  const preview = isDesktopDemoPath(window.location.pathname);
  const check = useMutation({
    mutationFn: () => preview
      ? Promise.resolve<UpdateSnapshot>({ status: "available", version: "0.1.1", notes: t("desktopUpdate.demoNotes") })
      : desktopInvoke<UpdateSnapshot>("desktop_check_update"),
  });
  const install = useMutation({
    mutationFn: () => preview ? Promise.resolve() : desktopInvoke<void>("desktop_install_update"),
  });
  const supported = preview || Boolean(window.__TAURI_INTERNALS__);
  return <section className="surface-panel settings-section" id="app-updates">
    <h2>{t("desktopUpdate.title")}</h2>
    <p className="field-help">{t("desktopUpdate.hint")}</p>
    {!supported && <p className="field-help">{t("desktopUpdate.nativeRequired")}</p>}
    {check.data && <p role="status">{t(`desktopUpdate.${check.data.status}`, { version: check.data.version })}</p>}
    {check.data?.notes && <p className="desktop-update-notes">{check.data.notes}</p>}
    {busy && <p className="field-help">{t("desktopUpdate.busy")}</p>}
    {install.isPending && <p role="status">{t("desktopUpdate.installing")}</p>}
    {install.isSuccess && <p role="status">{t(preview ? "desktopUpdate.demoInstalled" : "desktopUpdate.restarting")}</p>}
    {(check.error || install.error) && <p role="alert">{(check.error || install.error)?.message}</p>}
    <div className="settings-footer-actions">
      <button className="btn secondary" type="button" disabled={!supported || check.isPending || install.isPending || install.isSuccess}
        onClick={() => check.mutate()}>{t(check.isPending ? "common.loading" : "desktopUpdate.check")}</button>
      {check.data?.status === "available" && <button className="btn" type="button" disabled={busy || check.isPending || install.isPending || install.isSuccess}
        onClick={() => install.mutate()}>{t("desktopUpdate.install")}</button>}
    </div>
  </section>;
}
