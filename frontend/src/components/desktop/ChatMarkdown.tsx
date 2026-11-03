import { useMemo, useState } from "react";
import { cjk } from "@streamdown/cjk";
import { Streamdown, type StreamdownProps } from "streamdown";

import { useI18n } from "../../i18n";

const plugins = { cjk };

type ChatMarkdownProps = Pick<StreamdownProps, "children" | "mode" | "isAnimating">;

export function ChatMarkdown(props: ChatMarkdownProps): JSX.Element {
  const { t } = useI18n();
  const [copyFailed, setCopyFailed] = useState(false);
  const controls = useMemo(() => ({
    code: { copy: { onCopy: () => setCopyFailed(false), onError: () => setCopyFailed(true) }, download: false },
    table: false, mermaid: false, image: false,
  }), []);
  const translations = useMemo(() => ({
    copyCode: t("chat.code.copy"),
    openExternalLink: t("chat.link.confirm"),
    externalLinkWarning: t("chat.link.warning"),
    close: t("chat.link.close"),
    copyLink: t("chat.link.copy"),
    copied: t("chat.link.copied"),
    openLink: t("chat.link.open"),
  }), [t]);
  return <>
    <Streamdown {...props} plugins={plugins} translations={translations} controls={controls} tableMaxHeight={0} lineNumbers={false} />
    {copyFailed && <p className="chat-code-copy-error" role="alert">{t("chat.code.copyFailed")}</p>}
  </>;
}
