import SessionActivity from "./SessionActivity";
import {
  SidebarActivityProvider,
  useSessionActivity,
  useSidebarActivity,
  withWorkingSessions,
} from "../hooks/useSidebarActivity";
import {
  Fragment,
  memo,
  useCallback,
  useMemo,
  useState,
  useRef,
  useEffect,
} from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Dropdown } from "antd";
import type { MenuProps } from "antd";
import {
  Pencil,
  MoreHorizontal,
  Trash2,
  Pin,
  PinOff,
  MessageSquarePlus,
  Search,
  GitFork,
  Share2,
  Eye,
  EyeOff,
} from "lucide-react";
import type { Session } from "../hooks/useSessions";
import type { OctopAgent } from "../../../context/AgentContext";
import { isAgentChatReady } from "../../../utils/agentError";
import { showConfirmModal } from "../../../utils/confirmModal";
import ExpertAgentAvatar from "./ExpertAgentAvatar";
import type { ExpertPhase } from "../../../components/AnimatedExpertAvatar/model";
import { usePinnedExperts } from "../hooks/usePinnedExperts";
import {
  ExpertPinButton,
  ExpertStatusLabel,
  PinnedExperts,
  sidebarExpertPhase,
} from "./SidebarExpert";
import { useHiddenSharedExperts } from "../hooks/useHiddenSharedExperts";
import SessionChannelIcon from "./SessionChannelIcon";
import SharedExpertHint from "./SharedExpertHint";
import RemoteExpertHint from "./RemoteExpertHint";
import TeamChatBadge from "./TeamChatBadge";
import styles from "../index.module.less";

function AgentUnreadBadge({ count }: { count: number }) {
  const { t } = useTranslation();
  if (!count || count <= 0) return null;
  return (
    <span
      className={styles.agentUnreadBadge}
      aria-label={t("chat.unreadMessages", "未读消息")}
    >
      {count > 99 ? "99+" : count}
    </span>
  );
}

interface SessionItemProps {
  session: Session;
  isActive: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onPin: (id: string, pinned: boolean) => void;
  onFork: (id: string) => void;
  onShare?: (id: string, agentId?: string | null) => void;
  forkDisabled?: boolean;
  forkDisabledHint?: string;
}

const SessionItem = memo(function SessionItem({
  session,
  isActive,
  onSelect,
  onDelete,
  onRename,
  onPin,
  onFork,
  onShare,
  forkDisabled,
  forkDisabledHint,
}: SessionItemProps) {
  const { working } = useSessionActivity(session.id);
  const { t } = useTranslation();
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(session.name);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isEditing) setEditValue(session.name);
  }, [session.name, isEditing]);

  useEffect(() => {
    if (isEditing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [isEditing]);

  const commitEdit = useCallback(() => {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== session.name) {
      onRename(session.id, trimmed);
    } else {
      setEditValue(session.name);
    }
    setIsEditing(false);
  }, [editValue, session.name, session.id, onRename]);

  const itemForkDisabled = Boolean(forkDisabled) || !session.hasActivity;
  const itemForkHint = !session.hasActivity
    ? t("chat.forkNoAssistant")
    : forkDisabledHint;

  const menuItems: MenuProps["items"] = [
    ...(onShare
      ? [
          {
            key: "share",
            icon: <Share2 size={14} />,
            label: t("chatShare.title"),
            onClick: ({
              domEvent,
            }: {
              domEvent: Event | React.MouseEvent | React.KeyboardEvent;
            }) => {
              domEvent.stopPropagation();
              onShare(session.id);
            },
          },
        ]
      : []),
    {
      key: "pin",
      label: session.pinned
        ? t("chat.unpin", "取消置顶")
        : t("chat.pin", "置顶"),
      icon: session.pinned ? <PinOff size={14} /> : <Pin size={14} />,
      onClick: ({ domEvent }) => {
        domEvent.stopPropagation();
        onPin(session.id, !session.pinned);
      },
    },
    {
      key: "fork",
      label: t("chat.fork", "分叉"),
      icon: <GitFork size={14} />,
      disabled: itemForkDisabled,
      title: itemForkDisabled && itemForkHint ? itemForkHint : undefined,
      onClick: ({ domEvent }) => {
        domEvent.stopPropagation();
        onFork(session.id);
      },
    },
    {
      key: "rename",
      label: t("common.rename"),
      icon: <Pencil size={14} />,
      onClick: ({ domEvent }) => {
        domEvent.stopPropagation();
        setIsEditing(true);
      },
    },
    {
      key: "delete",
      label: t("common.delete", "Delete"),
      icon: <Trash2 size={14} />,
      danger: true,
      onClick: ({ domEvent }) => {
        domEvent.stopPropagation();
        showConfirmModal({
          title: t("chat.deleteSessionConfirm"),
          okText: t("common.delete"),
          cancelText: t("common.cancel"),
          okButtonProps: { danger: true },
          onOk: () => {
            onDelete(session.id);
          },
        });
      },
    },
  ];

  return (
    <div
      className={`${styles.sessionRow} ${
        isActive ? styles.sessionRowActive : ""
      } ${session.pinned ? styles.sessionRowPinned : ""} ${
        working ? styles.sessionRowWorking : ""
      }`}
      onClick={() => {
        if (!isEditing) onSelect(session.id);
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" && !isEditing) onSelect(session.id);
      }}
    >
      <SessionChannelIcon
        channelType={session.channelType}
        size={12}
        className={styles.sessionRowIcon}
      />
      {isEditing ? (
        <input
          ref={inputRef}
          className={styles.sessionNameInput}
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onBlur={commitEdit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitEdit();
            if (e.key === "Escape") {
              setEditValue(session.name);
              setIsEditing(false);
            }
          }}
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <>
          <span className={styles.sessionRowTitle}>{session.name}</span>
          <SessionActivity threadId={session.id} />
          {session.pinned ? (
            <span
              className={styles.sessionRowPinIndicator}
              title={t("chat.unpin")}
            >
              <Pin size={12} strokeWidth={2} />
            </span>
          ) : null}
          <Dropdown
            menu={{ items: menuItems }}
            trigger={["click"]}
            placement="bottomRight"
          >
            <button
              type="button"
              className={styles.sessionRowMore}
              aria-label={t("common.more", "More")}
              onClick={(e) => e.stopPropagation()}
            >
              <MoreHorizontal size={15} />
            </button>
          </Dropdown>
        </>
      )}
    </div>
  );
});

interface AgentCardProps {
  agent: OctopAgent;
  phase: ExpertPhase;
  pinned: boolean;
  onTogglePin: () => void;
  sessions: Session[];
  activeId: string | null;
  searchQuery: string;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  onFetchAllSessions: () => void;
  onSelect: (sessionId: string, agentId: string) => void;
  onNewChat: (agentId: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onPin: (id: string, pinned: boolean) => void;
  onFork: (id: string) => void;
  onShare?: (id: string, agentId?: string | null) => void;
  activeForkDisabled?: boolean;
  activeForkDisabledHint?: string;
  onHide?: () => void;
}

function ActiveAgentCard({
  agent,
  phase,
  pinned,
  onTogglePin,
  sessions,
  activeId,
  searchQuery,
  hasMore,
  loadingMore,
  onLoadMore,
  onFetchAllSessions,
  onSelect,
  onNewChat,
  onDelete,
  onRename,
  onPin,
  onFork,
  onShare,
  activeForkDisabled,
  activeForkDisabledHint,
  onHide,
}: AgentCardProps) {
  const { t } = useTranslation();

  const filteredSessions = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((s) => s.name.toLowerCase().includes(q));
  }, [sessions, searchQuery]);

  const fetchAllRequestedRef = useRef(false);
  useEffect(() => {
    const searching = Boolean(searchQuery.trim());
    if (!searching) {
      fetchAllRequestedRef.current = false;
      return;
    }
    if (fetchAllRequestedRef.current) return;
    fetchAllRequestedRef.current = true;
    onFetchAllSessions();
  }, [searchQuery, onFetchAllSessions]);

  const showExpandMore = hasMore && !searchQuery.trim();
  const sessionsEnabled = isAgentChatReady(agent.state);

  return (
    <div className={styles.agentCardActive}>
      <div
        className={styles.agentCardProfile}
        title={agent.description || undefined}
      >
        <ExpertAgentAvatar
          iconUrl={agent.icon_url}
          iconName={agent.icon_name}
          color={agent.color}
          size={44}
          phase={phase}
        />
        <div className={styles.agentCardInfo}>
          <div className={styles.agentCardNameRow}>
            <div className={styles.agentNameCluster}>
              <div className={styles.agentCardName}>{agent.name}</div>
              <TeamChatBadge agent={agent} />
              <SharedExpertHint agent={agent} />
              <RemoteExpertHint agent={agent} />
            </div>
            <AgentUnreadBadge count={agent.unread_count ?? 0} />
          </div>
          <div className={styles.expertRowStatus}>
            <ExpertStatusLabel phase={phase} />
            <ExpertPinButton pinned={pinned} onClick={onTogglePin} />
            <button
              type="button"
              className={styles.agentNewChatBtn}
              aria-label={t("chatWelcome.newChat")}
              title={t("chatWelcome.newChat")}
              onClick={(e) => {
                e.stopPropagation();
                onNewChat(agent.agent_id);
              }}
            >
              <MessageSquarePlus size={14} strokeWidth={1.75} aria-hidden />
            </button>
            {onHide ? (
              <button
                type="button"
                className={styles.agentHideBtn}
                aria-label={t("chat.expertHide")}
                title={t("chat.expertHide")}
                onClick={(e) => {
                  e.stopPropagation();
                  onHide();
                }}
              >
                <EyeOff size={14} aria-hidden />
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <div className={styles.agentCardSessions}>
        {!sessionsEnabled ? (
          <div className={styles.agentCardSessionsEmpty}>
            {t("chat.agentNotRunningHint")}
          </div>
        ) : sessions.length === 0 ? (
          <div className={styles.agentCardSessionsEmpty}>
            {t("chat.noSessionsYet", "直接发消息即可开始对话")}
          </div>
        ) : filteredSessions.length === 0 ? (
          <div className={styles.agentCardSessionsEmpty}>
            {t("chat.noSearchResults", "没有匹配的会话")}
          </div>
        ) : (
          <>
            {filteredSessions.map((s, index) => (
              <Fragment key={s.id}>
                {(index === 0 ||
                  Boolean(s.pinned) !==
                    Boolean(filteredSessions[index - 1].pinned)) && (
                  <div className={styles.sessionGroupTitle}>
                    {t(
                      s.pinned ? "chat.pinnedSessions" : "chat.recentSessions",
                    )}
                  </div>
                )}
                <SessionItem
                  key={s.id}
                  session={s}
                  isActive={activeId === s.id}
                  onSelect={(id) => onSelect(id, agent.agent_id)}
                  onDelete={onDelete}
                  onRename={onRename}
                  onPin={onPin}
                  onFork={onFork}
                  onShare={
                    onShare ? (id) => onShare(id, agent.agent_id) : undefined
                  }
                  forkDisabled={
                    activeId === s.id ? activeForkDisabled : undefined
                  }
                  forkDisabledHint={
                    activeId === s.id ? activeForkDisabledHint : undefined
                  }
                />
              </Fragment>
            ))}
            {showExpandMore ? (
              <button
                type="button"
                className={styles.sessionLoadMore}
                onClick={onLoadMore}
                disabled={loadingMore}
              >
                {loadingMore
                  ? t("common.loading")
                  : t("chat.expandMore", "展开更多")}
              </button>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

interface AgentRowProps {
  agent: OctopAgent;
  phase: ExpertPhase;
  pinned?: boolean;
  onTogglePin?: () => void;
  onSelect: () => void;
  onNewChat?: () => void;
  onHide?: () => void;
  onUnhide?: () => void;
}

function InactiveAgentRow({
  agent,
  phase,
  pinned = false,
  onTogglePin,
  onSelect,
  onNewChat,
  onHide,
  onUnhide,
}: AgentRowProps) {
  const { t } = useTranslation();

  return (
    <div className={styles.agentRowWrap}>
      <div
        className={styles.agentRow}
        title={agent.description || undefined}
        onClick={onSelect}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect();
          }
        }}
      >
        <ExpertAgentAvatar
          iconUrl={agent.icon_url}
          iconName={agent.icon_name}
          color={agent.color}
          size={44}
          phase={phase}
        />
        <div className={styles.agentRowInfo}>
          <div className={styles.agentRowNameRow}>
            <div className={styles.agentNameCluster}>
              <div className={styles.agentRowName}>{agent.name}</div>
              <TeamChatBadge agent={agent} />
              <SharedExpertHint agent={agent} />
              <RemoteExpertHint agent={agent} />
            </div>
            <AgentUnreadBadge count={agent.unread_count ?? 0} />
          </div>
          <div className={styles.expertRowStatus}>
            <ExpertStatusLabel phase={phase} />
            {onTogglePin && (
              <ExpertPinButton pinned={pinned} onClick={onTogglePin} />
            )}
            {onNewChat ? (
              <button
                type="button"
                className={styles.agentNewChatBtn}
                aria-label={t("chatWelcome.newChat")}
                title={t("chatWelcome.newChat")}
                onClick={(e) => {
                  e.stopPropagation();
                  onNewChat();
                }}
              >
                <MessageSquarePlus size={14} strokeWidth={1.75} aria-hidden />
              </button>
            ) : null}
          </div>
        </div>
      </div>
      {onHide ? (
        <button
          type="button"
          className={styles.agentHideBtn}
          aria-label={t("chat.expertHide")}
          title={t("chat.expertHide")}
          onClick={onHide}
        >
          <EyeOff size={14} aria-hidden />
        </button>
      ) : null}
      {onUnhide ? (
        <button
          type="button"
          className={styles.agentHideBtn}
          aria-label={t("chat.expertUnhide")}
          title={t("chat.expertUnhide")}
          onClick={onUnhide}
        >
          <Eye size={14} aria-hidden />
        </button>
      ) : null}
    </div>
  );
}

interface SessionListProps {
  agents: OctopAgent[];
  activePhase?: ExpertPhase;
  sessions: Session[];
  activeId: string | null;
  activeAgentId: string | null;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  onFetchAllSessions: () => void;
  onSelect: (sessionId: string, agentId: string) => void;
  onAgentSelect: (agentId: string) => void;
  onNewChat: (agentId: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onPin: (id: string, pinned: boolean) => void;
  onFork: (id: string) => void;
  onShare?: (id: string, agentId?: string | null) => void;
  activeForkDisabled?: boolean;
  activeForkDisabledHint?: string;
}

function SessionListContent({
  agents: initialAgents,
  activePhase,
  sessions: initialSessions,
  activeId,
  activeAgentId,
  hasMore,
  loadingMore,
  onLoadMore,
  onFetchAllSessions,
  onSelect,
  onAgentSelect,
  onNewChat,
  onDelete,
  onRename,
  onPin,
  onFork,
  onShare,
  activeForkDisabled,
  activeForkDisabledHint,
}: SessionListProps) {
  const { t } = useTranslation();
  const sidebarActivity = useSidebarActivity();
  const agents = initialAgents.map((agent) => ({
    ...agent,
    is_working:
      agent.is_working ||
      !!sidebarActivity[agent.agent_id]?.working_threads.length,
  }));
  const sessions = withWorkingSessions(
    initialSessions,
    sidebarActivity[activeAgentId ?? ""],
  );
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState("");
  const [showingHidden, setShowingHidden] = useState(false);
  const { pinnedIds, togglePin } = usePinnedExperts();
  const { filterVisible, pickHidden, hide, unhide, canHide } =
    useHiddenSharedExperts();

  const hiddenAgents = useMemo(
    () => [...pickHidden(agents)].sort((a, b) => b.id - a.id),
    [agents, pickHidden],
  );

  const sortedAgents = useMemo(() => {
    const visible = filterVisible(agents, {
      keepAgentIds: activeAgentId ? [activeAgentId] : [],
    });
    return [...visible].sort(
      (a, b) =>
        Number(b.kind === "team") - Number(a.kind === "team") || b.id - a.id,
    );
  }, [agents, filterVisible, activeAgentId]);

  // Leave the hidden-only view once nothing remains hidden.
  const viewingHidden = showingHidden && hiddenAgents.length > 0;
  const matchesAgent = (agent: OctopAgent) =>
    `${agent.name} ${agent.description || ""}`
      .toLowerCase()
      .includes(searchQuery.trim().toLowerCase());
  const agentsToRender = (viewingHidden ? hiddenAgents : sortedAgents).filter(
    (agent) => agent.agent_id === activeAgentId || matchesAgent(agent),
  );

  const expandedAgentId = useMemo(
    () =>
      viewingHidden ? null : activeAgentId ?? sortedAgents[0]?.agent_id ?? null,
    [activeAgentId, sortedAgents, viewingHidden],
  );
  const activeAgent = useMemo(
    () => sortedAgents.find((a) => a.agent_id === expandedAgentId) ?? null,
    [sortedAgents, expandedAgentId],
  );
  const showSessions = isAgentChatReady(activeAgent?.state);
  const pinnedAgents = pinnedIds.flatMap((id) => {
    const agent = sortedAgents.find((item) => item.agent_id === id);
    return agent && matchesAgent(agent) ? [agent] : [];
  });

  return (
    <div className={styles.sessionList}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 14px 18px",
        }}
      >
        <strong style={{ fontSize: 20 }}>{t("octopus.chat")}</strong>
        <button
          type="button"
          className={styles.sessionEmptyAgentsLink}
          onClick={() => navigate("/projects?new=1")}
        >
          {t("octopus.newGroupChat")}
        </button>
      </div>
      {showSessions ? (
        <div className={styles.sessionSearchWrap}>
          <Search
            size={14}
            className={styles.sessionSearchIcon}
            strokeWidth={2}
          />
          <input
            type="search"
            className={styles.sessionSearchInput}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t("chat.searchSessions", "搜索会话")}
            aria-label={t("chat.searchSessions", "搜索会话")}
          />
        </div>
      ) : null}

      {agents.length === 0 ? (
        <div className={styles.sessionEmptyAgents}>
          <p className={styles.sessionEmptyAgentsText}>
            {t("chat.noAgentsHint")}
          </p>
          <button
            type="button"
            className={styles.sessionEmptyAgentsLink}
            onClick={() => navigate("/experts")}
          >
            {t("chat.createExpert")}
          </button>
        </div>
      ) : (
        <div className={styles.sessionItems}>
          {!viewingHidden && (
            <PinnedExperts
              agents={pinnedAgents}
              activeAgentId={activeAgentId}
              activePhase={activePhase}
              onSelect={onAgentSelect}
              onTogglePin={togglePin}
            />
          )}
          {viewingHidden
            ? hiddenAgents.map((agent) => (
                <InactiveAgentRow
                  key={agent.agent_id}
                  agent={agent}
                  phase={sidebarExpertPhase(agent)}
                  onSelect={() => {
                    unhide(agent.agent_id);
                    setShowingHidden(false);
                    onAgentSelect(agent.agent_id);
                  }}
                  onUnhide={() => unhide(agent.agent_id)}
                />
              ))
            : agentsToRender.map((agent, index) => {
                const expanded = agent.agent_id === expandedAgentId;
                const row = expanded ? (
                  <ActiveAgentCard
                    key={agent.agent_id}
                    agent={agent}
                    phase={sidebarExpertPhase(agent, activePhase)}
                    pinned={pinnedIds.includes(agent.agent_id)}
                    onTogglePin={() => togglePin(agent.agent_id)}
                    sessions={sessions}
                    activeId={activeId}
                    searchQuery={matchesAgent(agent) ? "" : searchQuery}
                    hasMore={hasMore}
                    loadingMore={loadingMore}
                    onLoadMore={onLoadMore}
                    onFetchAllSessions={onFetchAllSessions}
                    onSelect={onSelect}
                    onNewChat={onNewChat}
                    onDelete={onDelete}
                    onRename={onRename}
                    onPin={onPin}
                    onFork={onFork}
                    onShare={onShare}
                    activeForkDisabled={activeForkDisabled}
                    activeForkDisabledHint={activeForkDisabledHint}
                    onHide={
                      canHide(agent) ? () => hide(agent.agent_id) : undefined
                    }
                  />
                ) : (
                  <InactiveAgentRow
                    key={agent.agent_id}
                    agent={agent}
                    phase={sidebarExpertPhase(agent)}
                    pinned={pinnedIds.includes(agent.agent_id)}
                    onTogglePin={() => togglePin(agent.agent_id)}
                    onSelect={() => onAgentSelect(agent.agent_id)}
                    onNewChat={() => onNewChat(agent.agent_id)}
                    onHide={
                      canHide(agent) ? () => hide(agent.agent_id) : undefined
                    }
                  />
                );
                const sectionStart =
                  index === 0 ||
                  (agent.kind === "team") !==
                    (agentsToRender[index - 1].kind === "team");
                return (
                  <Fragment key={agent.agent_id}>
                    {sectionStart && (
                      <div
                        style={{
                          padding: "14px 10px 8px",
                          fontSize: 11,
                          color: "var(--fn-text-secondary)",
                        }}
                      >
                        {t(
                          agent.kind === "team"
                            ? "octopus.groupChats"
                            : "octopus.privateChats",
                        )}
                      </div>
                    )}
                    {row}
                    {!expanded &&
                      withWorkingSessions(
                        [],
                        sidebarActivity[agent.agent_id],
                      ).map((session) => (
                        <button
                          key={session.id}
                          type="button"
                          className={`${styles.sessionRow} ${styles.sessionRowWorking} ${styles.backgroundSessionShortcut}`}
                          onClick={() => onSelect(session.id, agent.agent_id)}
                        >
                          <span className={styles.sessionRowTitle}>
                            {session.name}
                          </span>
                          <SessionActivity threadId={session.id} />
                        </button>
                      ))}
                  </Fragment>
                );
              })}
          {hiddenAgents.length > 0 ? (
            <button
              type="button"
              className={styles.expertHiddenToggle}
              onClick={() => setShowingHidden((v) => !v)}
            >
              {viewingHidden
                ? t("chat.expertListShowVisible")
                : t("chat.expertListHidden", { count: hiddenAgents.length })}
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
}

export default function SessionList(props: SessionListProps) {
  return (
    <SidebarActivityProvider agents={props.agents}>
      <SessionListContent {...props} />
    </SidebarActivityProvider>
  );
}
