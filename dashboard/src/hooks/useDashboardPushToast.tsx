import { App } from "antd";
import { Bell } from "lucide-react";
import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { buildDashboardNotifyWsUrl } from "../api/modules/wsNotifications";
import { getAuthToken } from "../api/request";
import { useAgent } from "../context/AgentContext";
import { ExpertIcon } from "../pages/Experts/components/iconForName";
import {
  emitSessionEvent,
  invalidateHistory,
} from "../pages/Chat/hooks/chatStore";
import {
  parseDashboardPushFrame,
  truncatePushText,
} from "../utils/dashboardPushToast";
import styles from "./useDashboardPushToast.module.less";

const PING_INTERVAL_MS = 25_000;
const MAX_RETRY_MS = 15_000;

function PushToastIcon({
  iconUrl,
  iconName,
}: {
  iconUrl?: string | null;
  iconName?: string | null;
}) {
  return (
    <span className={styles.icon}>
      {iconUrl || iconName ? (
        <ExpertIcon iconUrl={iconUrl} iconName={iconName} size={16} />
      ) : (
        <Bell size={16} />
      )}
    </span>
  );
}

/** Listen for dashboard text pushes and show a bottom-right toast. */
export function useDashboardPushToast(): void {
  const { notification } = App.useApp();
  const navigate = useNavigate();
  const location = useLocation();
  const routeRef = useRef(location.pathname);
  routeRef.current = location.pathname;
  const notices = useRef(new Map<string, Set<string>>());
  const visibleThread = useCallback(() => {
    if (document.hidden) return null;
    const match = /^\/chat\/([^/]+)\/([^/]+)\/?$/.exec(routeRef.current);
    return match
      ? `${decodeURIComponent(match[1])}\0${decodeURIComponent(match[2])}`
      : null;
  }, []);
  const clearVisibleNotices = useCallback(() => {
    const thread = visibleThread();
    if (!thread) return;
    for (const key of notices.current.get(thread) ?? [])
      notificationRef.current.destroy(key);
    notices.current.delete(thread);
  }, [visibleThread]);
  const { t } = useTranslation();
  const { refresh, agents } = useAgent();
  const agentsRef = useRef(agents);
  agentsRef.current = agents;
  const notificationRef = useRef(notification);
  notificationRef.current = notification;
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;
  const tRef = useRef(t);
  tRef.current = t;
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => {
    clearVisibleNotices();
  }, [location.pathname, clearVisibleNotices]);
  useEffect(() => {
    document.addEventListener("visibilitychange", clearVisibleNotices);
    return () =>
      document.removeEventListener("visibilitychange", clearVisibleNotices);
  }, [clearVisibleNotices]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 0;
    let reconnectTimer: number | null = null;

    const clearReconnect = () => {
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const scheduleReconnect = () => {
      if (closed) return;
      clearReconnect();
      const delay = Math.min(1000 * 2 ** retry, MAX_RETRY_MS);
      retry += 1;
      reconnectTimer = window.setTimeout(connect, delay);
    };

    const connect = () => {
      if (closed) return;
      const token = getAuthToken();
      if (!token) {
        scheduleReconnect();
        return;
      }
      let socket: WebSocket;
      try {
        socket = new WebSocket(buildDashboardNotifyWsUrl());
      } catch {
        scheduleReconnect();
        return;
      }
      if (ws && ws !== socket) {
        const prev = ws;
        ws = null;
        try {
          prev.close();
        } catch {
          // ignore
        }
      }
      ws = socket;
      socket.onopen = () => {
        retry = 0;
      };
      socket.onmessage = (event) => {
        let raw: unknown;
        try {
          raw = JSON.parse(String(event.data));
        } catch {
          return;
        }
        if (
          raw &&
          typeof raw === "object" &&
          (raw as { type?: string }).type === "pong"
        ) {
          return;
        }
        const parsed = parseDashboardPushFrame(raw);
        if (
          raw &&
          typeof raw === "object" &&
          (raw as { type?: string }).type === "thread_metadata.updated"
        ) {
          const frame = raw as { thread_id?: unknown; agent_id?: unknown };
          if (
            typeof frame.thread_id === "string" &&
            typeof frame.agent_id === "string"
          ) {
            emitSessionEvent({
              kind: "sessionsChanged",
              sessionId: frame.thread_id,
              agentId: frame.agent_id,
            });
          }
          return;
        }
        if (!parsed) return;
        void refreshRef.current({ silent: true });
        // A proactive run wrote to this thread outside the chat socket. Stale it
        // here (not in the chat page listener) so the cached page is dropped
        // even when the push lands while another route is open.
        invalidateHistory(parsed.thread_id);
        // Refresh the sidebar and the open thread's history without a reload.
        emitSessionEvent({
          kind: "sessionsChanged",
          sessionId: parsed.thread_id,
          agentId: parsed.agent_id,
        });
        const threadKey = `${parsed.agent_id}\0${parsed.thread_id}`;
        if (visibleThread() === threadKey) {
          clearVisibleNotices();
          return;
        }
        const agent = agentsRef.current.find(
          (a) => a.agent_id === parsed.agent_id,
        );
        const accent = agent?.color?.trim() || "#6366f1";
        const title = parsed.agent_name
          ? tRef.current("chat.pushToast.title", { name: parsed.agent_name })
          : tRef.current("chat.pushToast.titleFallback");
        const noticeKey = `dash-push-${parsed.thread_id}-${Date.now()}`;
        const keys = notices.current.get(threadKey) ?? new Set<string>();
        keys.add(noticeKey);
        notices.current.set(threadKey, keys);
        const forget = () => {
          keys.delete(noticeKey);
          if (!keys.size) notices.current.delete(threadKey);
        };
        notificationRef.current.open({
          key: noticeKey,
          placement: "bottomRight",
          className: styles.notice,
          style: {
            ["--push-accent" as string]: accent,
          },
          message: (
            <span className={styles.header}>
              <PushToastIcon
                iconUrl={agent?.icon_url}
                iconName={agent?.icon_name}
              />
              <span className={styles.title}>{title}</span>
            </span>
          ),
          description: (
            <span className={styles.body}>{truncatePushText(parsed.text)}</span>
          ),
          duration: null,
          closable: true,
          onClose: forget,
          onClick: () => {
            forget();
            notificationRef.current.destroy(noticeKey);
            navigateRef.current(`/chat/${parsed.agent_id}/${parsed.thread_id}`);
          },
        });
      };
      socket.onclose = () => {
        if (ws !== socket) return;
        ws = null;
        if (!closed) scheduleReconnect();
      };
    };

    connect();
    const pingTimer = window.setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify({ type: "ping" }));
        } catch {
          // ignore
        }
      }
    }, PING_INTERVAL_MS);

    return () => {
      closed = true;
      clearReconnect();
      window.clearInterval(pingTimer);
      if (ws) {
        try {
          ws.close();
        } catch {
          // ignore
        }
      }
    };
  }, [clearVisibleNotices, visibleThread]);
}
