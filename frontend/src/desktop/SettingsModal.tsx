import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { SettingsWorkspace } from "./SettingsWorkspace";
import { SettingsDraftsProvider, useSettingsDrafts } from "./SettingsDrafts";
import { useI18n } from "../i18n";
import { desktopLinkPath, type DesktopBasePath } from "./location";
import "../components/desktop/settings-modal.css";

type SettingsModalProps = { basePath: DesktopBasePath; theme: "light" | "dark";
  onThemeChange: (theme: "light" | "dark") => void; statusLabel: string };

function DiscardDrafts({ cancel, discard }: { cancel: () => void; discard: () => void }): JSX.Element {
  const { t } = useI18n();
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    return () => element.close();
  }, []);
  return <dialog ref={dialog} className="desktop-discard-dialog" aria-labelledby="desktop-discard-title"
    onCancel={(event) => { event.preventDefault(); cancel(); }}>
    <h2 id="desktop-discard-title">{t("settings.unsavedChanges")}</h2>
    <p>{t("desktop.preferences.discardHint")}</p>
    <div className="desktop-discard-actions">
      <button type="button" className="btn secondary" autoFocus onClick={cancel}>{t("desktop.preferences.keepEditing")}</button>
      <button type="button" className="btn" onClick={discard}>{t("settings.discard")}</button>
    </div>
  </dialog>;
}

function SettingsModalContent({ basePath, theme, onThemeChange, statusLabel }: SettingsModalProps): JSX.Element {
  const { t } = useI18n();
  const navigate = useNavigate();
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef(document.activeElement as HTMLElement | null);
  const drafts = useSettingsDrafts()!;
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const leave = () => navigate(desktopLinkPath(basePath));

  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    return () => {
      element.close();
      opener.current?.focus();
    };
  }, []);

  function close() {
    if (drafts.pending) return;
    const review = Array.from(dialog.current?.querySelectorAll('[role="dialog"], dialog[open]') ?? [])
      .some((element) => !element.closest("[hidden]"));
    if (review) return;
    if (drafts.dirty) setConfirmDiscard(true); else leave();
  }

  return <dialog ref={dialog} className="desktop-settings-modal" aria-labelledby="desktop-settings-title"
    onCancel={(event) => { event.preventDefault(); close(); }}>
    <header className="desktop-settings-header">
      <h1 id="desktop-settings-title">{t("desktop.settings.title")}</h1>
      <button type="button" className="desktop-settings-close" disabled={drafts.pending} onClick={close} aria-label={t("chat.link.close")} autoFocus>
        <X size={18} aria-hidden="true" />
      </button>
    </header>
    <SettingsWorkspace basePath={basePath} theme={theme} onThemeChange={onThemeChange} statusLabel={statusLabel} />
    {confirmDiscard && <DiscardDrafts cancel={() => setConfirmDiscard(false)} discard={leave} />}
  </dialog>;
}

export function SettingsModal(props: SettingsModalProps): JSX.Element {
  return <SettingsDraftsProvider><SettingsModalContent {...props} /></SettingsDraftsProvider>;
}
