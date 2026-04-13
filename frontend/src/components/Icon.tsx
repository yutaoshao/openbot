type IconName =
  | "dashboard"
  | "chat"
  | "conversations"
  | "memory"
  | "tools"
  | "scheduler"
  | "monitoring"
  | "logs"
  | "settings"
  | "search"
  | "notifications"
  | "help"
  | "spark"
  | "shield"
  | "rocket";

const ICONS: Record<IconName, JSX.Element> = {
  dashboard: (
    <>
      <rect x="3" y="3" width="8" height="8" rx="2" />
      <rect x="13" y="3" width="8" height="5" rx="2" />
      <rect x="13" y="10" width="8" height="11" rx="2" />
      <rect x="3" y="13" width="8" height="8" rx="2" />
    </>
  ),
  chat: (
    <>
      <path d="M5 6.5A2.5 2.5 0 0 1 7.5 4h9A2.5 2.5 0 0 1 19 6.5v6A2.5 2.5 0 0 1 16.5 15H11l-4 3v-3H7.5A2.5 2.5 0 0 1 5 12.5z" />
    </>
  ),
  conversations: (
    <>
      <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h6A2.5 2.5 0 0 1 15 6.5v4A2.5 2.5 0 0 1 12.5 13H9l-3 2v-2h.5A2.5 2.5 0 0 1 4 10.5z" />
      <path d="M10 11.5A2.5 2.5 0 0 0 12.5 14H16l2 2v-2a2.5 2.5 0 0 0 2.5-2.5v-3A2.5 2.5 0 0 0 18 6h-1" />
    </>
  ),
  memory: (
    <>
      <path d="M7 5.5A2.5 2.5 0 0 1 9.5 3h5A2.5 2.5 0 0 1 17 5.5v1A2.5 2.5 0 0 1 14.5 9h-5A2.5 2.5 0 0 1 7 6.5z" />
      <path d="M5 13a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v2.5A3.5 3.5 0 0 1 15.5 19h-7A3.5 3.5 0 0 1 5 15.5z" />
    </>
  ),
  tools: (
    <>
      <path d="m13.5 5 5.5 5.5-2 2-5.5-5.5z" />
      <path d="M11 13 5 19l-2-2 6-6" />
      <path d="m14 4 2-2 4 4-2 2" />
    </>
  ),
  scheduler: (
    <>
      <rect x="4" y="5" width="16" height="15" rx="3" />
      <path d="M8 3v4M16 3v4M4 10h16" />
    </>
  ),
  monitoring: (
    <>
      <path d="M4 18h16" />
      <path d="M6 15.5 10 11l3 3 5-6" />
      <circle cx="10" cy="11" r="1" fill="currentColor" stroke="none" />
      <circle cx="13" cy="14" r="1" fill="currentColor" stroke="none" />
      <circle cx="18" cy="8" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  logs: (
    <>
      <path d="M5 6h14M5 12h14M5 18h9" />
      <rect x="3" y="3" width="18" height="18" rx="3" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3.5" />
      <path d="M12 3v2.5M12 18.5V21M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M3 12h2.5M18.5 12H21M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="6" />
      <path d="m20 20-4.2-4.2" />
    </>
  ),
  notifications: (
    <>
      <path d="M12 4a4 4 0 0 1 4 4v2.5c0 .8.3 1.5.8 2.1l1 1.1H6.2l1-1.1c.5-.6.8-1.3.8-2.1V8a4 4 0 0 1 4-4" />
      <path d="M10 17a2 2 0 0 0 4 0" />
    </>
  ),
  help: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.6 9.2a2.7 2.7 0 1 1 4.7 1.7c-.7.7-1.8 1.2-1.8 2.6" />
      <circle cx="12" cy="16.8" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  spark: (
    <>
      <path d="m12 3 1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3 6 5.5V11c0 4.2 2.4 7.2 6 9 3.6-1.8 6-4.8 6-9V5.5z" />
      <path d="m9.5 11.8 1.7 1.7 3.3-3.6" />
    </>
  ),
  rocket: (
    <>
      <path d="M14 4c3.5 0 6 2.5 6 6-2 .4-3.6.8-5 2.2L12 15l-3.2-3.2C10.2 9.8 10.6 8 11 6c1.3-1.3 2-2 3-2Z" />
      <path d="m8 16-2 5 5-2" />
      <path d="M14.5 9.5h.01" />
    </>
  ),
};

export function Icon({ name, className }: { name: IconName; className?: string }): JSX.Element {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
      aria-hidden="true"
    >
      {ICONS[name]}
    </svg>
  );
}

export type { IconName };
