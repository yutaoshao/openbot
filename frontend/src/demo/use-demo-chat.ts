import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { recordDemoTurn } from "./backend";
import type { DemoDetail, DemoPhase, DemoScenario } from "./chat-types";

type SimulatedRun = {
  controller: AbortController;
  conversationId: string | null;
  input: string;
  output: string;
};

function waitForFrame(signal: AbortSignal, delay: number): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(signal.reason); return; }
    const abort = () => { window.clearTimeout(timer); reject(signal.reason); };
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, delay);
    signal.addEventListener("abort", abort, { once: true });
  });
}

/** Entirely synthetic execution; the real Agent cancellation contract is a later phase. */
export function useDemoChat() {
  const { t } = useI18n();
  const cache = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>("demo-weekly");
  const [scenario, setScenario] = useState<DemoScenario>("ready");
  const [phase, setPhase] = useState<DemoPhase>("idle");
  const [pendingInput, setPendingInput] = useState("");
  const [output, setOutput] = useState("");
  const [stoppedId, setStoppedId] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const active = useRef<SimulatedRun | null>(null);
  const detail = useQuery({
    queryKey: ["conversation", selectedId],
    enabled: !!selectedId,
    queryFn: () => api.get<DemoDetail>(`/api/conversations/${selectedId}`),
  });

  useEffect(() => () => { active.current?.controller.abort(); active.current = null; }, []);

  const selectConversation = (id: string | null) => {
    if (active.current) return;
    setFailure(null);
    setSelectedId(id);
    setScenario("ready");
  };

  const chooseScenario = (next: DemoScenario) => {
    if (active.current) return;
    setScenario(next);
    if (next === "empty") setSelectedId(null);
  };

  const finish = async (run: SimulatedRun, stopped: boolean) => {
    if (active.current !== run) return;
    try {
      const id = recordDemoTurn(run.conversationId, run.input, run.output || t("desktop.emptyStopped"));
      setStoppedId(stopped ? id : null);
      setSelectedId(id);
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["conversations"] }),
        cache.invalidateQueries({ queryKey: ["conversation", id] }),
      ]);
    } catch {
      setFailure(t("desktop.saveError"));
      setSelectedId(null);
    } finally {
      if (active.current === run) {
        active.current = null;
        setPhase("idle");
        setPendingInput("");
        setOutput("");
      }
    }
  };

  const submit = async (text: string) => {
    const input = text.trim();
    if (!input || active.current || ["starting", "offline", "error"].includes(scenario)) return;
    const run: SimulatedRun = { controller: new AbortController(), conversationId: selectedId, input, output: "" };
    active.current = run;
    setFailure(null);
    setPendingInput(input);
    setOutput("");
    setPhase("tool");
    const reply = t(scenario === "long" ? "desktop.longReply" : "desktop.reply");
    try {
      await waitForFrame(run.controller.signal, 850);
      setPhase("streaming");
      for (let end = 4; end < reply.length + 4; end += 4) {
        await waitForFrame(run.controller.signal, 32);
        run.output = reply.slice(0, end);
        setOutput(run.output);
      }
      await finish(run, false);
    } catch {
      if (active.current === run) await finish(run, true);
    }
  };

  const stop = () => {
    if (!active.current || phase === "stopping") return;
    setPhase("stopping");
    active.current.controller.abort();
  };

  return {
    selectedId, scenario, phase, pendingInput, output, failure,
    messages: detail.data?.messages ?? [],
    title: detail.data?.conversation.title ?? t("desktop.newChat"),
    loading: detail.isPending && !!selectedId,
    error: detail.isError,
    stopped: stoppedId === selectedId && selectedId !== null,
    busy: phase !== "idle",
    selectConversation, chooseScenario, submit, stop, reconnect: () => chooseScenario("ready"),
  };
}

export type DemoChat = ReturnType<typeof useDemoChat>;
