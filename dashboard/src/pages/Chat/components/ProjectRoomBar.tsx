import { useEffect, useState } from "react";
import { Avatar, Button, Dropdown, Popover, Space, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { AtSign, KanbanSquare, UserPlus, Activity } from "lucide-react";
import { teamsApi, type TeamRecord } from "../../../api/modules/teams";
import { useAgent } from "../../../context/AgentContext";
import { ExpertIcon } from "../../Experts/components/iconForName";
import styles from "../index.module.less";
import { onToolEvent } from "../hooks/chatStore";

export default function ProjectRoomBar({
  teamId,
  compact = false,
  onMention,
  onConfigureMember,
}: {
  teamId: string;
  compact?: boolean;
  onMention: (name: string) => void;
  onConfigureMember: (agentId: string) => void;
}) {
  const { t } = useTranslation();
  const { setActiveAgent } = useAgent();
  const navigate = useNavigate();
  const [room, setRoom] = useState<TeamRecord | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    let mounted = true;
    let version = 0;
    const load = () => {
      const requestVersion = ++version;
      void teamsApi
        .get(teamId)
        .then((value) => {
          if (mounted && requestVersion === version) {
            setRoom(value);
            setUnavailable(false);
          }
        })
        .catch(() => {
          if (mounted && requestVersion === version) setUnavailable(true);
        });
    };
    load();
    const offTool = onToolEvent((event) => {
      if (
        event.kind === "toolDone" &&
        event.toolName.startsWith("octop_project_")
      )
        load();
    });
    const timer = window.setInterval(load, 10000);
    return () => {
      mounted = false;
      offTool();
      window.clearInterval(timer);
    };
  }, [teamId]);
  if (unavailable)
    return (
      <div style={{ padding: "8px 20px" }}>
        <Tag>{t("octopus.loadFailed")}</Tag>
      </div>
    );
  if (!room) return null;
  const go = (id: string, path: string) => {
    setActiveAgent(id);
    navigate(path);
  };
  const members = (
    <div style={{ width: 300, maxHeight: 420, overflow: "auto" }}>
      {room.members.map((member) => (
        <Dropdown
          key={member.agent_id}
          menu={{
            items: [
              {
                key: "mention",
                icon: <AtSign size={14} />,
                label: `@ ${member.name}`,
                onClick: () => onMention(member.name),
              },
              {
                key: "chat",
                label: t("octopus.privateChat"),
                onClick: () => go(member.agent_id, `/chat/${member.agent_id}`),
              },
              {
                key: "profile",
                label: t("octopus.configuration"),
                onClick: () => onConfigureMember(member.agent_id),
              },
              {
                key: "history",
                label: t("octopus.chatHistory"),
                onClick: () => go(member.agent_id, `/chat/${member.agent_id}`),
              },
              {
                key: "tasks",
                label: t("octopus.memberReports"),
                onClick: () =>
                  navigate(
                    `/task-board?project=${teamId}&agent=${member.agent_id}`,
                  ),
              },
            ],
          }}
          trigger={["click"]}
        >
          <button
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              border: 0,
              background: "transparent",
              color: "inherit",
              padding: 12,
              width: "100%",
              cursor: "pointer",
              textAlign: "left",
            }}
          >
            <Avatar
              src={
                member.icon_url ? (
                  <ExpertIcon
                    iconUrl={member.icon_url}
                    size={32}
                    phase={member.busy ? "running" : "idle"}
                  />
                ) : undefined
              }
              style={{ background: member.color || "#7471cf" }}
            >
              {member.name[0]}
            </Avatar>
            <span style={{ flex: 1 }}>{member.name}</span>
            <Tag color={member.busy ? "gold" : undefined}>
              {t(`octopus.${member.busy ? "executing" : "idle"}`)}
            </Tag>
          </button>
        </Dropdown>
      ))}
    </div>
  );
  return (
    <div
      className={compact ? styles.roomActions : undefined}
      style={
        compact
          ? undefined
          : {
              padding: "10px 20px",
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              borderBottom: "1px solid var(--fn-border-color,#e8e9ed)",
            }
      }
    >
      {!compact ? (
        <Button
          type="text"
          onClick={() => navigate(`/projects?project=${teamId}`)}
        >
          <Space direction="vertical" size={0} style={{ textAlign: "left" }}>
            <strong>{room.name}</strong>
            <small style={{ color: "var(--fn-text-secondary)" }}>
              {room.members.filter((member) => member.busy).length
                ? t("octopus.membersWorking", {
                    count: room.members.filter((member) => member.busy).length,
                  })
                : t("octopus.idle")}
            </small>
          </Space>
        </Button>
      ) : null}
      <Space wrap>
        <Button
          type="text"
          size="small"
          icon={<Activity size={14} />}
          aria-label={t("octopus.usage")}
          title={t("octopus.usage")}
          onClick={() => go(teamId, "/token-usage")}
        >
          {t("octopus.usage")}
        </Button>
        <Button
          type="text"
          size="small"
          icon={<UserPlus size={14} />}
          aria-label={t("octopus.manageMembers")}
          title={t("octopus.manageMembers")}
          onClick={() => navigate(`/projects?project=${teamId}&edit=1`)}
        >
          {t("octopus.manageMembers")}
        </Button>
        <Button
          size="small"
          icon={<KanbanSquare size={14} />}
          aria-label={t("octopus.board")}
          title={t("octopus.board")}
          onClick={() => navigate(`/task-board?project=${teamId}`)}
        >
          {t("octopus.board")}
        </Button>
        <Popover
          title={`${t("octopus.members")} · ${room.members.length}`}
          content={members}
          trigger="click"
          placement="bottomRight"
        >
          <button
            aria-label={t("octopus.members")}
            style={{ border: 0, background: "transparent", cursor: "pointer" }}
          >
            <Avatar.Group maxCount={4} size={28}>
              {room.members.map((member) => (
                <Avatar
                  key={member.agent_id}
                  src={
                    member.icon_url ? (
                      <ExpertIcon
                        iconUrl={member.icon_url}
                        size={28}
                        phase={member.busy ? "running" : "idle"}
                        animated={member.busy}
                      />
                    ) : undefined
                  }
                  style={{ background: member.color || "#7471cf" }}
                >
                  {member.name[0]}
                </Avatar>
              ))}
            </Avatar.Group>
          </button>
        </Popover>
      </Space>
    </div>
  );
}
