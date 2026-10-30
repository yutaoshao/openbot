import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "../i18n";
import { api } from "../lib/api";

type LoginSession = {
  session_id: string;
  status: "wait" | "scanned" | "confirmed" | "expired" | "cancelled" | "failed";
  qr_image?: string;
  expires_in?: number;
};
const active = (session: LoginSession | null | undefined) => session?.status === "wait" || session?.status === "scanned";

export function WeChatLogin({ enabled, loggedIn }: { enabled: boolean; loggedIn: boolean }) {
  const { t } = useI18n();
  const cache = useQueryClient();
  const [session, setSession] = useState<LoginSession | null>(null);
  const alive = useRef(false);
  const current = useRef<LoginSession | null>(null);
  const poll = useQuery({
    queryKey: ["desktop-wechat-login", session?.session_id],
    queryFn: () => api.get<LoginSession>(`/api/desktop/wechat/login/${encodeURIComponent(session!.session_id)}`),
    enabled: active(session), retry: false,
    refetchInterval: (query) => active(query.state.data ?? session) ? 1500 : false,
  });
  const displayed = (active(session) && poll.data?.session_id === session?.session_id ? poll.data : session) ?? null;
  current.current = displayed;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (active(current.current)) void api.del(`/api/desktop/wechat/login/${encodeURIComponent(current.current!.session_id)}`).catch(() => {});
    };
  }, []);
  useEffect(() => {
    if (displayed?.status === "confirmed") void cache.invalidateQueries({ queryKey: ["desktop-services"] });
  }, [displayed?.status, cache]);
  const begin = useMutation({
    mutationFn: () => api.post<LoginSession>("/api/desktop/wechat/login", {}),
    onSuccess: (next) => {
      if (!alive.current) { void api.del(`/api/desktop/wechat/login/${encodeURIComponent(next.session_id)}`).catch(() => {}); return; }
      setSession(next);
    },
  });
  const cancel = useMutation({
    mutationFn: async (sessionId: string) => {
      const result = await api.del<LoginSession>(`/api/desktop/wechat/login/${encodeURIComponent(sessionId)}`);
      if (result.session_id !== sessionId) throw new Error(t("desktopServices.loginStateChanged"));
      return result;
    },
    onSuccess: (result, requested) => { if (session?.session_id === requested) setSession(result); },
  });
  return <section className="surface-panel settings-section" id="wechat-login">
    <h2>{t("desktop.wechatLogin")}</h2>
    <p className="field-help">{t(loggedIn ? "desktopServices.wechatLoggedIn" : "desktopServices.wechatLoginHint")}</p>
    {enabled && <p className="field-help">{t("desktopServices.wechatDisableFirst")}</p>}
    {displayed && <p role="status">{t(`desktopServices.login.${displayed.status}`)}</p>}
    {active(displayed) && session?.qr_image?.startsWith("data:image/png;base64,") && <img
      className="desktop-login-qr" src={session.qr_image} alt={t("desktop.wechatLogin")} width={240} height={240} />}
    <div className="settings-footer-actions">
      <button className="btn secondary" type="button" disabled={enabled || begin.isPending || active(displayed) || cancel.isPending}
        onClick={() => begin.mutate()}>{t(begin.isPending ? "common.loading" : "desktopServices.startLogin")}</button>
      {active(displayed) && <button className="btn ghost" type="button" disabled={cancel.isPending} onClick={() => cancel.mutate(session!.session_id)}>{t("desktopServices.cancelLogin")}</button>}
      {poll.isError && active(displayed) && <button className="btn ghost" type="button" onClick={() => void poll.refetch()}>{t("desktopServices.checkLogin")}</button>}
    </div>
    {(begin.error || cancel.error || poll.error) && <p role="alert">{(begin.error || cancel.error || poll.error)?.message}</p>}
  </section>;
}
