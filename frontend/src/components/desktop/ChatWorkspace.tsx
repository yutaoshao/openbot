import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowDown, ChevronDown, FileSearch, LoaderCircle, RotateCcw } from "lucide-react";
import { Streamdown } from "streamdown";

import { useI18n } from "../../i18n";
import { Button } from "../ui/button";
import { ChatComposer } from "./ChatComposer";
import type { ChatViewModel } from "./chat-view";

export function ChatWorkspace({ chat }: { chat: ChatViewModel }): JSX.Element {
  const { t } = useI18n();
  const scroll = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const [showLatest, setShowLatest] = useState(false);
  const [toolOpen, setToolOpen] = useState(false);
  const prepend = useRef<{ height: number; top: number; firstId?: string } | null>(null);
  const unavailable = ["starting", "offline", "error"].includes(chat.scenario);

  useEffect(() => {
    following.current = true;
    setShowLatest(false);
    if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [chat.selectedId]);

  useEffect(() => {
    if (scroll.current && following.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [chat.output, chat.messages, chat.pendingInput, chat.phase]);
  useLayoutEffect(() => {
    const before = prepend.current;
    const node = scroll.current;
    if (before && node && before.firstId !== chat.messages[0]?.id) {
      node.scrollTop = before.top + node.scrollHeight - before.height;
      following.current = false;
      prepend.current = null;
    }
  }, [chat.messages]);

  return (
    <section className="demo-chat" aria-label={t("nav.chat")}>
      <div className="demo-messages-scroll" ref={scroll} onScroll={() => {
        const node = scroll.current;
        if (!node) return;
        following.current = node.scrollHeight - node.scrollTop - node.clientHeight < 72;
        setShowLatest(!following.current);
      }}>
        <div className="demo-conversation-column">
          {unavailable ? <div className="demo-service-message" role="status">
            {chat.scenario === "starting" && <LoaderCircle className="demo-spinner" size={20} />}
            <h2>{t(`desktop.state.${chat.scenario}`)}</h2>
            <p>{t(`desktop.detail.${chat.scenario}`)}</p>
            {chat.scenario !== "starting" && <Button variant="outline" onClick={() => chat.reconnect?.()}>
              <RotateCcw size={14} />{t("desktop.reconnect")}
            </Button>}
          </div> : <>
            {chat.loading && <p className="demo-muted" role="status">{t("common.loading")}</p>}
            {chat.error && <div role="alert"><p>{t("desktop.historyError")}</p>
              {chat.reloadHistory && <Button variant="outline" onClick={() => void chat.reloadHistory?.()}>{t("desktop.reconnect")}</Button>}
            </div>}
            {chat.failure && <div className="demo-turn-error" role="alert"><p>{chat.failure}</p>
              {chat.recover && <Button variant="outline" onClick={() => void chat.recover?.()}>{t("desktopLive.checkRun")}</Button>}
              {chat.withdraw && <div><p>{t("desktopLive.withdrawHint")}</p>
                <Button variant="outline" disabled={chat.withdrawing} onClick={() => void chat.withdraw?.()}>{t(chat.withdrawing ? "common.loading" : "desktopLive.withdraw")}</Button></div>}
            </div>}
            {!chat.loading && chat.messages.length === 0 && !chat.busy && <div className="demo-empty">
              <h1>{t("desktop.welcome")}</h1><p>{t("desktop.welcomeHint")}</p>
              <Button variant="outline" onClick={() => void chat.submit(t("desktop.suggestionPrompt"))}>
                {t("desktop.suggestion")}
              </Button>
            </div>}
            {chat.hasEarlier && <Button variant="outline" disabled={chat.loadingEarlier} onClick={() => {
              if (scroll.current) prepend.current = { height: scroll.current.scrollHeight, top: scroll.current.scrollTop, firstId: chat.messages[0]?.id };
              void Promise.resolve(chat.loadEarlier?.()).catch(() => { prepend.current = null; });
            }}>{t(chat.loadingEarlier ? "common.loading" : "desktopLive.loadEarlier")}</Button>}
            {chat.messages.map((message) => <article key={message.id}
              className={`demo-message demo-message-${message.role}`} aria-label={t(`chat.role.${message.role}`)}>
              {message.role === "user" ? <p>{message.content}</p> :
                <Streamdown mode="static" controls={false}>{message.content}</Streamdown>}
              {message.outcome && <p className="demo-stopped" role="status">{t(message.outcome === "cancelled" ? "desktopLive.historyStopped" : "desktopLive.historyIncomplete")}</p>}
            </article>)}
            {chat.pendingInput && <article className="demo-message demo-message-user"><p>{chat.pendingInput}</p></article>}
            {chat.busy && <div className="demo-active-reply" aria-busy="true">
              <button className="demo-tool-status" type="button" onClick={() => setToolOpen((value) => !value)}
                aria-expanded={toolOpen}>
                {chat.phase === "tool" ? <FileSearch size={14} /> : <LoaderCircle className="demo-spinner" size={14} />}
                {chat.phaseLabel ?? t(`desktop.phase.${chat.phase}`)}<ChevronDown size={12} />
              </button>
              {toolOpen && <p className="demo-tool-detail">{chat.toolDetail ?? t("desktop.toolDetail")}</p>}
              {chat.output && <div className="demo-message demo-message-assistant">
                <Streamdown mode="streaming" isAnimating controls={false}>{chat.output}</Streamdown>
              </div>}
            </div>}
            {!chat.busy && chat.stopped && <p className="demo-stopped" role="status">{chat.stoppedDetail ?? t("desktop.stopped")}</p>}
          </>}
        </div>
      </div>
      {showLatest && <Button className="demo-jump-latest" variant="outline" size="icon"
        aria-label={t("desktop.latest")} onClick={() => {
          following.current = true;
          setShowLatest(false);
          if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
        }}><ArrowDown size={15} /></Button>}
      <ChatComposer chat={chat} />
    </section>
  );
}
