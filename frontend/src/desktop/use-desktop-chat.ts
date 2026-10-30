import { useEffect, useRef, useState } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ChatMessage, ChatViewModel } from "../components/desktop/chat-view";
import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { earlierHistoryPage, historyMessages, loadHistoryPage, type HistoryPageParam } from "./history";
import { forgetPendingRequest, readPendingRequest, rememberPendingRequest, samePendingRequest, type PendingRequest } from "./pending-request";
import { terminalRun, type ChatRun } from "./types";

const SELECTION_KEY = "openbot_desktop_selection_v1";
type Submission = { message: string; conversation_id?: string; request_id: string };
const errorText = (error: unknown): string => error instanceof Error ? error.message : String(error);

function readUnconfirmed(instanceId: string): { pending: PendingRequest | null; stale: PendingRequest | null } {
  const value = readPendingRequest();
  return value?.instance_id === instanceId ? { pending: value, stale: null } : { pending: null, stale: value };
}

export function useDesktopChat(instanceId: string): ChatViewModel {
  const { t } = useI18n();
  const cache = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(() => localStorage.getItem(SELECTION_KEY));
  const [runId, setRunId] = useState<string | null>(null);
  const [pendingInput, setPendingInput] = useState("");
  const [recoveryState] = useState(() => readUnconfirmed(instanceId));
  const [failure, setFailure] = useState<string | null>(recoveryState.stale ? t("desktopLive.serviceRestarted") : null);
  const [stopped, setStopped] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [stopPending, setStopPending] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const [lastReply, setLastReply] = useState<{ conversationId: string; message: ChatMessage } | null>(null);
  const [uncertain, setUncertain] = useState<{ request_id: string } | null>(recoveryState.pending);
  const inFlight = useRef(false);
  const stopRequested = useRef(false);
  const withdrawalInFlight = useRef<PendingRequest | null>(null);
  const finalized = useRef<string | null>(null);
  const currentInstance = useRef(instanceId);
  currentInstance.current = instanceId;
  const currentRequest = useRef<PendingRequest | null>(recoveryState.pending);
  const currentRun = useRef<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (selectedId) localStorage.setItem(SELECTION_KEY, selectedId);
    else localStorage.removeItem(SELECTION_KEY);
  }, [selectedId]);
  useEffect(() => {
    if (recoveryState.stale) forgetPendingRequest(recoveryState.stale);
  }, [recoveryState]);
  const isCurrentInstance = () => mounted.current && currentInstance.current === instanceId;
  const isCurrentPending = (owner: PendingRequest) => isCurrentInstance()
    && samePendingRequest(currentRequest.current, owner) && samePendingRequest(readPendingRequest(), owner);

  const history = useInfiniteQuery({
    queryKey: ["desktop-history", selectedId],
    enabled: !!selectedId,
    initialPageParam: null as HistoryPageParam | null,
    queryFn: async ({ pageParam }) => {
      try { return await loadHistoryPage(selectedId!, pageParam); }
      catch (error) {
        if ((runId || submitting) && errorText(error).startsWith("404:")) {
          return { conversation: { id: selectedId!, title: null, message_count: 0 }, messages: [], offset: 0, missing: true };
        }
        throw error;
      }
    },
    getNextPageParam: earlierHistoryPage,
  });
  const runQuery = useQuery({
    queryKey: ["desktop-run", runId],
    enabled: !!runId,
    queryFn: () => api.get<ChatRun>(`/api/chat/runs/${encodeURIComponent(runId!)}`),
    refetchInterval: (query) => query.state.data && terminalRun(query.state.data) ? false : 350,
    retry: false,
  });
  const existing = useQuery({
    queryKey: ["desktop-active-runs", selectedId],
    enabled: !!selectedId && !runId && !submitting && !uncertain,
    queryFn: () => api.get<ChatRun[]>(`/api/chat/runs?conversation_id=${encodeURIComponent(selectedId!)}`),
    staleTime: 0,
  });
  useEffect(() => {
    if (lastReply && history.isSuccess) setLastReply(null);
  }, [lastReply, history.isSuccess]);
  useEffect(() => {
    const missing = history.data?.pages[0]?.missing
      || (history.isError && errorText(history.error).startsWith("404:"));
    if (!selectedId || !missing || runId || submitting || uncertain || inFlight.current
      || !existing.isFetched || existing.isFetching || existing.isError
      || existing.data?.some((run) => !terminalRun(run))) return;
    setSelectedId(null); setPendingInput(""); setLastReply(null);
    if (!stopped) setFailure(t("desktopLive.historyMissing"));
  }, [selectedId, history.data, history.isError, history.error, runId, submitting, uncertain,
    existing.data, existing.isFetched, existing.isFetching, existing.isError, stopped, t]);

  const acceptRun = (run: ChatRun, owner?: PendingRequest) => {
    if (!isCurrentInstance() || (owner && !isCurrentPending(owner))) return false;
    if (owner) forgetPendingRequest(owner);
    currentRun.current = run.run_id;
    cache.setQueryData(["desktop-run", run.run_id], run);
    setSelectedId(run.conversation_id);
    setRunId(run.run_id);
    setUncertain(null);
    setFailure(null);
    finalized.current = null;
    return true;
  };
  useEffect(() => {
    if (runId || submitting || uncertain || inFlight.current || existing.isFetching || !existing.isFetched || existing.isError) return;
    const active = existing.data?.find((run) => !terminalRun(run));
    if (active) acceptRun(active);
  }, [existing.data, existing.isFetching, existing.isFetched, existing.isError, runId, submitting, uncertain]);

  useEffect(() => {
    const run = runQuery.data;
    if (!run || !terminalRun(run) || finalized.current === run.run_id) return;
    finalized.current = run.run_id;
    void (async () => {
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["conversations"] }),
        cache.invalidateQueries({ queryKey: ["desktop-history", run.conversation_id] }),
        cache.invalidateQueries({ queryKey: ["conversation", run.conversation_id] }),
        cache.invalidateQueries({ queryKey: ["desktop-active-runs", run.conversation_id] }),
      ]);
      if (!isCurrentInstance() || currentRun.current !== run.run_id) return;
      setLastReply(run.text && cache.getQueryState(["desktop-history", run.conversation_id])?.status === "error" ? { conversationId: run.conversation_id, message: {
        id: run.run_id, role: "assistant", content: run.text,
        outcome: run.status === "cancelled" ? "cancelled" : run.status === "failed" ? "failed" : undefined,
      } } : null);
      setStopped(run.status === "cancelled");
      setFailure(run.status === "failed" ? run.error || t("desktopLive.runFailed") : null);
      setRunId(null);
      setPendingInput("");
      setStopPending(false);
      setSubmitting(false);
      currentRun.current = null;
      currentRequest.current = null;
      stopRequested.current = false;
      inFlight.current = false;
    })();
  }, [runQuery.data, cache, t]);

  const recover = async (): Promise<ChatRun | undefined> => {
    if (!isCurrentInstance()) return;
    if (!uncertain) {
      if (!runId) return;
      const result = await runQuery.refetch();
      return isCurrentInstance() && currentRun.current === runId ? result.data : undefined;
    }
    const owner = { request_id: uncertain.request_id, instance_id: instanceId };
    if (!isCurrentPending(owner)) return;
    try {
      const rows = await api.get<ChatRun[]>(`/api/chat/runs?request_id=${encodeURIComponent(uncertain.request_id)}`);
      if (!isCurrentPending(owner)) return;
      const found = rows.find((run) => run.request_id === uncertain.request_id);
      if (found) {
        if (!acceptRun(found, owner)) return;
        if (stopRequested.current) await requestStop(found);
        return found;
      }
      setFailure(t("desktopLive.runNotFound"));
    } catch { if (isCurrentPending(owner)) setFailure(t("desktopLive.runUnknown")); }
  };

  const submit = async (text: string) => {
    const message = text.trim();
    if (!isCurrentInstance() || !message || inFlight.current || runId || uncertain) return;
    inFlight.current = true;
    const submission: Submission = { message, request_id: crypto.randomUUID(), ...(selectedId ? { conversation_id: selectedId } : {}) };
    const owner = { request_id: submission.request_id, instance_id: instanceId };
    currentRequest.current = owner;
    rememberPendingRequest(owner);
    setSubmitting(true); setStopped(false); setFailure(null); setPendingInput(message);
    setLastReply(null);
    setStopPending(false); stopRequested.current = false;
    try {
      const run = await api.post<ChatRun>("/api/chat/runs", submission);
      if (isCurrentPending(owner)) {
        acceptRun(run, owner);
        if (stopRequested.current) await requestStop(run);
      }
    } catch (error) {
      if (!isCurrentPending(owner)) return;
      if (/^(400|401|403|404|409|422):/.test(errorText(error))) {
        forgetPendingRequest(owner);
        setStopPending(false); stopRequested.current = false;
        setFailure(errorText(error)); setPendingInput(""); inFlight.current = false;
      } else {
        setUncertain({ request_id: submission.request_id }); setFailure(t("desktopLive.runUnknown"));
      }
    } finally { if (isCurrentInstance() && samePendingRequest(currentRequest.current, owner)) setSubmitting(false); }
  };

  const requestStop = async (target: ChatRun) => {
    if (!isCurrentInstance() || currentRun.current !== target.run_id) return;
    if (terminalRun(target) || target.status === "stopping") return;
    try {
      const run = await api.post<ChatRun>(`/api/chat/runs/${encodeURIComponent(target.run_id)}/stop`, {});
      if (!isCurrentInstance() || currentRun.current !== target.run_id) return;
      cache.setQueryData(["desktop-run", target.run_id], run);
    } catch (error) {
      if (!isCurrentInstance() || currentRun.current !== target.run_id) return;
      setStopPending(false); stopRequested.current = false;
      setFailure(`${t("desktopLive.stopFailed")} ${errorText(error)}`);
    }
  };
  const withdraw = async () => {
    if (!uncertain || withdrawalInFlight.current) return;
    const owner = { request_id: uncertain.request_id, instance_id: instanceId };
    if (!isCurrentPending(owner)) return;
    withdrawalInFlight.current = owner; setWithdrawing(true);
    try {
      const result = await api.post<ChatRun | { request_id: string; status: "not_accepted" | "expired" }>(
        `/api/chat/requests/${encodeURIComponent(uncertain.request_id)}/stop`, {},
      );
      if (!isCurrentPending(owner)) return;
      if ("run_id" in result) {
        if (!acceptRun(result, owner)) return;
        stopRequested.current = true; setStopPending(true);
      } else if (result.status === "not_accepted" || result.status === "expired") {
        forgetPendingRequest(owner);
        currentRequest.current = null;
        setUncertain(null); setPendingInput(""); setRunId(null); setStopPending(false);
        setFailure(result.status === "expired" ? t("desktopLive.expiredRequest") : null);
        inFlight.current = false; stopRequested.current = false;
        await Promise.all([
          cache.invalidateQueries({ queryKey: ["conversations"] }),
          ...(selectedId ? [cache.invalidateQueries({ queryKey: ["desktop-history", selectedId] })] : []),
        ]);
      }
    } catch {
      if (isCurrentPending(owner)) setFailure(t("desktopLive.withdrawUnknown"));
    } finally {
      if (samePendingRequest(withdrawalInFlight.current, owner)) {
        withdrawalInFlight.current = null;
        if (isCurrentInstance()) setWithdrawing(false);
      }
    }
  };
  const stop = () => {
    setStopPending(true); stopRequested.current = true;
    if (runQuery.data) void requestStop(runQuery.data);
    else if (uncertain) void recover();
    else if (!submitting) void recover().then((target) => { if (target) void requestStop(target); });
  };

  const run = runQuery.data;
  const messages = historyMessages([...(history.data?.pages ?? [])].reverse().flatMap((page) => page.messages));
  if (history.isError && lastReply?.conversationId === selectedId) messages.push(lastReply.message);
  const last = messages[messages.length - 1];
  if ((runId || submitting) && pendingInput && last?.role === "user" && last.content === pendingInput) messages.pop();
  const activeTools = run?.tool_events ?? [];
  const phase = stopPending || run?.status === "stopping" ? "stopping" : run?.status === "queued" || submitting || uncertain ? "queued"
    : activeTools[activeTools.length - 1]?.status === "running" ? "tool" : runId ? "streaming" : "idle";
  return {
    selectedId, title: history.data?.pages[0]?.conversation.title || t("desktop.newChat"),
    scenario: "ready", phase, messages, pendingInput, output: run?.text ?? "", stopped,
    stoppedDetail: t("desktopLive.stoppedDetail"),
    phaseLabel: uncertain ? t("desktopLive.runUnknownLabel") : stopPending && !run
      ? t("desktopLive.stopRequested") : phase === "tool" ? t("desktopLive.toolRunning", { name: activeTools[activeTools.length - 1]?.name }) : undefined,
    busy: !!runId || submitting || !!uncertain, loading: history.isPending && !!selectedId,
    error: history.isError && !(runId && errorText(history.error).startsWith("404:")),
    failure: failure || (uncertain || runQuery.isError ? t("desktopLive.runUnknown") : null),
    toolDetail: activeTools.length ? activeTools.map((event) => `${event.name}: ${["running", "finished", "failed", "interrupted"].includes(event.status) ? t(`desktopLive.toolState.${event.status}`) : event.status}${event.text ? ` · ${event.text}` : ""}`).join("\n") : t("desktopLive.waitingReply"),
    selectConversation: (id) => {
      if (inFlight.current || runId || uncertain) return;
      setSelectedId(id); setStopped(false); setFailure(null); setPendingInput(""); setLastReply(null);
    },
    submit, stop, recover: uncertain || runQuery.isError ? async () => { await recover(); } : undefined,
    withdraw: uncertain ? withdraw : undefined, withdrawing,
    hasEarlier: history.hasNextPage, loadingEarlier: history.isFetchingNextPage,
    loadEarlier: () => history.fetchNextPage(),
    reloadHistory: () => history.refetch(),
  };
}
