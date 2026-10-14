import { Button, Dropdown } from "antd";
import {
  ArrowUpRight,
  File,
  Info,
  Laptop,
  Monitor,
  MoreHorizontal,
  Pencil,
  RefreshCw,
  Shield,
  Terminal,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Device } from "../../api/modules/devices";
import { formatServerDateTime } from "../../utils/formatMessageTime";
import { supportsWorkspaceView, type DeviceWorkspaceView } from "./helpers";

export default function DeviceCard({
  device,
  timezone,
  onOpen,
  onDetails,
  onSettings,
  onRename,
  onRefresh,
  onRevoke,
}: {
  device: Device;
  timezone: string;
  onOpen: (view: DeviceWorkspaceView) => void;
  onDetails: () => void;
  onSettings: () => void;
  onRename: () => void;
  onRefresh: () => void;
  onRevoke: () => void;
}) {
  const { t } = useTranslation();
  const state =
    device.revoked_at !== null
      ? "revoked"
      : device.online
      ? "online"
      : "offline";
  const views = [
    { key: "files" as const, icon: File, label: t("devices.filesTab") },
    { key: "desktop" as const, icon: Monitor, label: t("devices.desktopTab") },
    { key: "command" as const, icon: Terminal, label: t("devices.commandTab") },
  ].filter(({ key }) => supportsWorkspaceView(device, key));
  const platform =
    { linux: "Linux", windows: "Windows", darwin: "macOS" }[
      device.platform.toLowerCase()
    ] ?? device.platform;
  return (
    <article className="devices-device-card" aria-label={device.name}>
      <div className="devices-card-heading">
        <div className="devices-card-icon">
          {device.platform.toLowerCase().includes("linux") ? (
            <Terminal size={23} strokeWidth={1.6} />
          ) : (
            <Laptop size={23} strokeWidth={1.6} />
          )}
        </div>
        <div className="devices-card-identity">
          <h2 title={device.name}>{device.name}</h2>
          <div className="devices-card-meta">
            <span>{platform}</span>
            <span aria-hidden>·</span>
            <span>
              {t("devices.sharedFolderCount", { count: device.roots.length })}
            </span>
          </div>
        </div>
        <span className="devices-connection-status" data-state={state}>
          <i aria-hidden />
          {t(`devices.${state}`)}
        </span>
        <Dropdown
          overlayClassName="devices-action-menu"
          trigger={["click"]}
          menu={{
            items: [
              {
                key: "details",
                label: t("devices.details"),
                icon: <Info size={16} />,
              },
              {
                key: "rename",
                label: t("devices.rename"),
                icon: <Pencil size={16} />,
                disabled: device.revoked_at !== null,
              },
              {
                key: "refresh",
                label: t("devices.refresh"),
                icon: <RefreshCw size={16} />,
              },
              { type: "divider" },
              {
                key: "revoke",
                label: t("devices.revoke"),
                icon: <Trash2 size={16} />,
                danger: true,
                disabled: device.revoked_at !== null,
              },
            ],
            onClick: ({ key }) => {
              if (key === "details") onDetails();
              if (key === "rename") onRename();
              if (key === "refresh") onRefresh();
              if (key === "revoke") onRevoke();
            },
          }}
        >
          <Button
            type="text"
            icon={<MoreHorizontal size={18} />}
            aria-label={t("devices.deviceActions", { name: device.name })}
          />
        </Dropdown>
      </div>
      <div className="devices-card-footer">
        <div className="devices-card-context">
          <div className="devices-roster-grants">
            {device.permissions.length ? (
              device.permissions.map((permission) => (
                <span key={permission}>
                  {t(`devices.permissions.${permission}`, {
                    defaultValue: permission,
                  })}
                </span>
              ))
            ) : (
              <span>{t("devices.noAuthorizedTools")}</span>
            )}
          </div>
          <span className="devices-last-seen">
            {t("devices.lastSeen")} ·{" "}
            {device.last_seen_at
              ? formatServerDateTime(device.last_seen_at, timezone)
              : t("devices.neverSeen")}
          </span>
        </div>
        <div className="devices-card-actions">
          {views.map(({ key, icon: Icon, label }) => (
            <Button
              type="text"
              size="small"
              key={key}
              icon={<Icon size={14} />}
              onClick={() => onOpen(key)}
            >
              {label}
            </Button>
          ))}
          <Button
            type="text"
            size="small"
            icon={<Shield size={14} />}
            onClick={onSettings}
          >
            {t("devices.settingsTab")}
          </Button>
          <Button
            className="devices-open-workspace"
            disabled={!views.length}
            onClick={() => {
              if (views[0]) onOpen(views[0].key);
            }}
          >
            {t("devices.openWorkspace")}
            <ArrowUpRight size={14} />
          </Button>
        </div>
      </div>
    </article>
  );
}
