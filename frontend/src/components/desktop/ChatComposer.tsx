import { useState } from "react";
import { ArrowUp, Square } from "lucide-react";

import { useI18n } from "../../i18n";
import { Button } from "../ui/button";
import { PromptInput, PromptInputTextarea } from "../prompt-kit/prompt-input";
import type { ChatViewModel } from "./chat-view";

export function ChatComposer({ chat }: { chat: ChatViewModel }): JSX.Element {
  const { t } = useI18n();
  const [value, setValue] = useState("");
  const unavailable = ["starting", "offline", "error"].includes(chat.scenario);
  const send = () => {
    if (!value.trim() || chat.busy || unavailable) return;
    void chat.submit(value);
    setValue("");
  };

  return (
    <div className="demo-composer-dock">
      <PromptInput value={value} onValueChange={setValue} onSubmit={send}
        disabled={unavailable} maxHeight={180} className="demo-composer">
        <PromptInputTextarea aria-label={t("desktop.input")}
          placeholder={t("desktop.placeholder")} className="demo-composer-textarea" />
        <Button type="button" size="icon" className="demo-send"
          aria-label={t(chat.busy ? "desktop.stop" : "desktop.send")}
          title={t(chat.busy ? "desktop.stop" : "desktop.send")}
          disabled={unavailable || (chat.busy ? chat.phase === "stopping" : !value.trim())}
          onClick={(event) => { event.stopPropagation(); if (chat.busy) chat.stop(); else send(); }}>
          {chat.busy ? <Square size={13} fill="currentColor" /> : <ArrowUp size={17} />}
        </Button>
      </PromptInput>
      <p className="demo-input-hint">{t("desktop.inputHint")}</p>
    </div>
  );
}
