const DEFAULT_RETRY_COUNT = 1;
const DEFAULT_RETRY_DELAY_MS = 800;
const OPERATOR_STALE_TIME_MS = 30_000;
const METRICS_STALE_TIME_MS = 15_000;

export const operatorQueryDefaults = {
  refetchOnWindowFocus: false,
  retry: DEFAULT_RETRY_COUNT,
  retryDelay: DEFAULT_RETRY_DELAY_MS,
  staleTime: OPERATOR_STALE_TIME_MS,
} as const;

export const metricsQueryDefaults = {
  ...operatorQueryDefaults,
  staleTime: METRICS_STALE_TIME_MS,
} as const;

export const liveLogsQueryDefaults = {
  ...operatorQueryDefaults,
  refetchIntervalInBackground: false,
} as const;
