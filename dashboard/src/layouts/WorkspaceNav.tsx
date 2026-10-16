import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import {
  MessageSquare,
  Users,
  Bot,
  Activity,
  Settings2,
  X,
  Sparkles,
  Wrench,
  Puzzle,
  Brain,
  Notebook,
  Waypoints,
} from "lucide-react";
import { Button, Tooltip } from "antd";
import { useCurrentUser } from "../hooks/useCurrentUser";
import { useServerCapabilities } from "../hooks/useServerCapabilities";
import { buildNavSections, type NavItem } from "./sidebarNav";
import AvatarDropdown from "../components/AvatarDropdown";
import "./workspaceNav.css";

const groups = [
  { id: "chat", icon: MessageSquare, path: "/chat", keys: ["chat"] },
  {
    id: "projects",
    icon: Users,
    path: "/projects",
    keys: ["projects", "task-board", "tasks"],
  },
  {
    id: "agents",
    icon: Bot,
    path: "/experts",
    keys: [
      "experts",
      "personalization",
      "channels",
      "connectors",
      "skill-packages",
      "knowledge-bases",
    ],
  },
  {
    id: "operations",
    icon: Activity,
    path: "/devices",
    keys: ["token-usage", "context-insights", "devices", "workbench", "remote-desktop", "acp"],
  },
  {
    id: "settings",
    icon: Settings2,
    path: "/admin/models",
    keys: [
      "models",
      "bridge",
      "admin-users",
      "admin-storage",
      "admin-plugins",
      "admin-security",
      "admin-advanced",
      "agent-config",
    ],
  },
];
export default function WorkspaceNav({
  selectedKey,
  collapsed,
  isMobile,
  onToggle,
}: {
  selectedKey: string;
  collapsed: boolean;
  isMobile: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const user = useCurrentUser();
  const { mobileEnabled } = useServerCapabilities();
  const active =
    groups.find((group) => group.keys.includes(selectedKey)) || groups[0];
  const catalog = buildNavSections(user, { mobileEnabled }).flatMap(
    (section) => section.items,
  );
  const extra: NavItem[] = [
    {
      key: "projects",
      path: "/projects",
      labelKey: "octopus.projects",
      icon: <Users size={17} />,
    },
    {
      key: "task-board",
      path: "/task-board",
      labelKey: "octopus.board",
      icon: <Activity size={17} />,
    },
  ];
  const available = [...extra, ...catalog];
  const context = available.filter((item) => active.keys.includes(item.key));
  const inChat = active.id === "chat";
  const deviceWorkspace =
    location.pathname === "/devices" &&
    Boolean(new URLSearchParams(location.search).get("device")) &&
    ["desktop", "files", "command"].includes(
      new URLSearchParams(location.search).get("view") ?? "",
    );
  return (
    <div
      className={`octopus-workspace-nav ${isMobile ? "mobile" : ""} ${
        isMobile && collapsed ? "closed" : ""
      }`}
    >
      <nav className="octopus-icon-rail" aria-label={t("octopus.navigation")}>
        <button
          className="octopus-brand"
          onClick={() => navigate("/projects")}
          aria-label="Octopus"
        >
          O<span />
        </button>
        {groups.map((group) => {
          const Icon = group.icon;
          const first = available.find((item) => group.keys.includes(item.key));
          return (
            first && (
              <Tooltip
                key={group.id}
                title={t(`octopus.${group.id}`)}
                placement="right"
              >
                <button
                  className={active.id === group.id ? "active" : ""}
                  onClick={() =>
                    navigate(
                      available.find((item) => item.path === group.path)
                        ?.path || first.path,
                    )
                  }
                  aria-label={t(`octopus.${group.id}`)}
                  aria-current={active.id === group.id ? "page" : undefined}
                >
                  <Icon size={21} strokeWidth={1.6} />
                  {active.id === group.id && (
                    <span>{t(`octopus.${group.id}`)}</span>
                  )}
                </button>
              </Tooltip>
            )
          );
        })}
        <div className="octopus-rail-account">
          <AvatarDropdown user={user} placement="sidebar" compact />
        </div>
      </nav>
      {(!inChat || isMobile) && (!deviceWorkspace || isMobile) && (
        <aside className="octopus-context-nav">
          <header>
            <div>
              <strong>{t(`octopus.${active.id}`)}</strong>
            </div>
            {isMobile && (
              <Button
                type="text"
                aria-label={t("common.close")}
                icon={<X size={16} />}
                onClick={onToggle}
              />
            )}
          </header>
          {context
            .filter(
              (item) =>
                !["workbench", "remote-desktop"].includes(item.key) &&
                (active.id !== "agents" ||
                  !["personalization", "channels"].includes(item.key)),
            )
            .map((item) => (
              <button
                key={item.key}
                className={
                  selectedKey === item.key ||
                  (item.key === "devices" &&
                    ["workbench", "remote-desktop"].includes(selectedKey))
                    ? "active"
                    : ""
                }
                onClick={() => {
                  navigate(item.path);
                  if (isMobile) onToggle();
                }}
              >
                {item.icon}
                <span>{t(item.labelKey)}</span>
              </button>
            ))}
          {active.id === "agents" && (
            <div className="octopus-context-subnav">
              <small>{t("personalization.title")}</small>
              {[
                { key: "skills", icon: Sparkles },
                { key: "subagents", icon: Bot },
                { key: "tools", icon: Wrench },
                { key: "plugins", icon: Puzzle },
                { key: "mbti", icon: Brain },
                { key: "memory", icon: Notebook },
                ...(available.some((item) => item.key === "channels")
                  ? [{ key: "channels", icon: Waypoints }]
                  : []),
              ].map(({ key, icon: Icon }) => (
                <button
                  key={key}
                  className={
                    location.pathname.endsWith(`/${key}`) ? "active" : ""
                  }
                  onClick={() => navigate(`/personalization/${key}`)}
                >
                  <Icon size={17} />
                  <span>{t(`personalization.tabs.${key}`)}</span>
                </button>
              ))}
            </div>
          )}
        </aside>
      )}
    </div>
  );
}
