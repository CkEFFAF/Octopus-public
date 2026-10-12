import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Empty,
  Input,
  InputNumber,
  Modal,
  Drawer,
  Progress,
  Select,
  Segmented,
  Tag,
} from "antd";
import {
  ArrowLeft,
  Copy,
  Globe,
  History,
  Smartphone,
  File,
  Laptop,
  Link2,
  Monitor,
  RefreshCw,
  Shield,
  Terminal,
  Trash2,
} from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { useServerCapabilities } from "../../hooks/useServerCapabilities";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../utils/formatMessageTime";
import { userCan } from "../../utils/permissions";
import { useTranslation } from "react-i18next";
import PageShell from "../../layouts/PageShell";
import { getApiUrl } from "../../api/config";
import {
  devicesApi,
  type Device,
  type DeviceOperation,
} from "../../api/modules/devices";
import { apiErrorMessage } from "../../utils/apiError";
import { copyText } from "../../utils/copyText";
import DeviceDesktop from "./DeviceDesktop";
import DeviceFiles from "./DeviceFiles";
import AccessKeys from "./AccessKeys";
import {
  canUse,
  formatBytes,
  permissionKeys,
  selectedDeviceId,
  deviceWorkspaceUrl,
  workspaceView,
  supportsWorkspaceView,
  type DeviceWorkspaceView,
} from "./helpers";
import "./devices.css";

function DeviceSettings({
  device,
  onChanged,
  onError,
}: {
  device: Device;
  onChanged: (device: Device) => void;
  onError: (error: unknown) => void;
}) {
  const { t } = useTranslation();
  const { modal } = App.useApp();
  const [name, setName] = useState(device.name);
  const [permissions, setPermissions] = useState(device.permissions);
  const [busy, setBusy] = useState(false);
  return (
    <div className="devices-tool">
      <label className="devices-field">
        <span>{t("devices.deviceName")}</span>
        <Input
          value={name}
          maxLength={100}
          disabled={device.revoked_at !== null}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <h3>{t("devices.permissionsTitle")}</h3>
      <p className="devices-muted">{t("devices.grantHint", t("devices.reduceHint"))}</p>
      {device.pending_proposal && (
        <Alert
          type="info"
          showIcon
          message={t("devices.pendingGrant")}
        />
      )}
      {device.permissions.includes("acp_run") && (
        <Alert type="warning" showIcon message={t("devices.acpRunHint")} />
      )}
      <div className="devices-permissions">
        {permissionKeys.map((permission) => (
          <Checkbox
            key={permission}
            checked={permissions.includes(permission)}
            disabled={
              device.revoked_at !== null ||
              !device.capabilities.includes(permission) ||
              (permission === "desktop_control" &&
                !permissions.includes("desktop_view"))
            }
            onChange={(event) =>
              setPermissions((current) => {
                const next = event.target.checked
                  ? [...current, permission]
                  : current.filter((value) => value !== permission);
                return permission === "desktop_view" && !event.target.checked
                  ? next.filter((value) => value !== "desktop_control")
                  : next;
              })
            }
          >
            {t(`devices.permissions.${permission}`)}
            {!device.capabilities.includes(permission) && (
              <small> · {t("devices.unsupported")}</small>
            )}
          </Checkbox>
        ))}
      </div>
      <Button
        type="primary"
        loading={busy}
        disabled={device.revoked_at !== null || !name.trim()}
        onClick={async () => {
          setBusy(true);
          try {
            onChanged(
              await devicesApi.update(device.device_id, {
                name: name.trim(),
                permissions,
              }),
            );
          } catch (error) {
            onError(error);
          } finally {
            setBusy(false);
          }
        }}
      >
        {t("devices.saveDevice")}
      </Button>
      <h3>{t("devices.sharedRoots")}</h3>
      {device.roots.length === 0 && (
        <p className="devices-muted">{t("devices.noRoots")}</p>
      )}
      {device.roots.map((root) => (
        <div className="devices-root" key={root.id}>
          <strong>{root.name}</strong>
          <span className="devices-path">{root.path}</span>
          <div>
            {root.read && <Tag>{t("devices.read")}</Tag>}
            {root.write && <Tag>{t("devices.write")}</Tag>}
          </div>
        </div>
      ))}
      <Button
        danger
        icon={<Trash2 size={16} />}
        disabled={device.revoked_at !== null}
        onClick={() =>
          modal.confirm({
            title: t("devices.revokeTitle", { name: device.name }),
            content: t("devices.revokeHint"),
            okText: t("devices.revoke"),
            cancelText: t("common.cancel"),
            okButtonProps: { danger: true },
            onOk: async () => {
              try {
                onChanged(await devicesApi.revoke(device.device_id));
              } catch (error) {
                onError(error);
                throw error;
              }
            },
          })
        }
      >
        {t("devices.revoke")}
      </Button>
    </div>
  );
}

function DeviceCommand({
  device,
  onError,
  onOperation,
}: {
  device: Device;
  onError: (error: unknown) => void;
  onOperation: (operation: DeviceOperation) => void;
}) {
  const { t } = useTranslation();
  const [rootId, setRootId] = useState(device.roots[0]?.id ?? "");
  const [argv, setArgv] = useState('["python", "script.py"]');
  const [timeout, setTimeoutValue] = useState(60);
  const [busy, setBusy] = useState(false);
  return (
    <div className="devices-tool">
      <Alert type="info" showIcon message={t("devices.commandHint")} />
      <label className="devices-field">
        <span>{t("devices.workingRoot")}</span>
        <Select
          aria-label={t("devices.workingRoot")}
          value={rootId || undefined}
          onChange={setRootId}
          options={device.roots.map((root) => ({
            value: root.id,
            label: root.name,
          }))}
        />
      </label>
      <label className="devices-field">
        <span>{t("devices.argv")}</span>
        <Input.TextArea
          value={argv}
          autoSize={{ minRows: 3, maxRows: 8 }}
          onChange={(event) => setArgv(event.target.value)}
        />
      </label>
      <label className="devices-field">
        <span>{t("devices.timeout")}</span>
        <InputNumber
          value={timeout}
          min={1}
          max={3600}
          onChange={(value) => setTimeoutValue(value ?? 60)}
        />
      </label>
      <Button
        disabled={!canUse(device, "command_exec") || !rootId}
        loading={busy}
        onClick={async () => {
          setBusy(true);
          try {
            const parsed: unknown = JSON.parse(argv);
            if (
              !Array.isArray(parsed) ||
              !parsed.length ||
              parsed.some((value) => typeof value !== "string") ||
              !(parsed[0] as string).trim()
            )
              throw new Error(t("devices.invalidArgv"));
            onOperation(
              await devicesApi.submit(device.device_id, "command.run", {
                root_id: rootId,
                argv: parsed,
                timeout,
              }),
            );
          } catch (error) {
            onError(error);
          } finally {
            setBusy(false);
          }
        }}
      >
        {t("devices.submitCommand")}
      </Button>
    </div>
  );
}

export default function DevicesPage() {
  const { t } = useTranslation();
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const [query, setQuery] = useSearchParams();
  const user = useCurrentUser();
  const { mobileEnabled } = useServerCapabilities();
  const serverTimezone = useServerTimezone();
  const requestedId = query.get("device") ?? "";
  const view = workspaceView(query.get("view"));
  const inWorkspace = Boolean(requestedId && view);
  const [devices, setDevices] = useState<Device[]>([]);
  const [selected, setSelected] = useState("");
  const [operations, setOperations] = useState<DeviceOperation[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [pairingOpen, setPairingOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [pairing, setPairing] = useState<{
    pairing_code: string;
    expires_at: number;
  } | null>(null);
  const [pairingBusy, setPairingBusy] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [operationBusy, setOperationBusy] = useState("");
  const refreshPending = useRef(false);
  const device = devices.find(
    (item) => item.device_id === (inWorkspace ? requestedId : selected),
  );
  const onError = useCallback(
    (err: unknown) =>
      setError(apiErrorMessage(err, t("devices.requestFailed"), t)),
    [t],
  );
  const refresh = useCallback(async () => {
    if (refreshPending.current) return;
    refreshPending.current = true;
    setLoading(true);
    try {
      const [nextDevices, nextOperations] = await Promise.all([
        devicesApi.list(),
        devicesApi.operations(),
      ]);
      setDevices(nextDevices.devices);
      setSelected((current) => selectedDeviceId(nextDevices.devices, current));
      setOperations(nextOperations.operations);
      setLoaded(true);
    } catch (err) {
      onError(err);
    } finally {
      refreshPending.current = false;
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!document.hidden) await refresh();
      if (active) timer = setTimeout(poll, 5000);
    };
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [refresh]);

  useEffect(() => {
    if (!pairingOpen) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [pairingOpen]);

  useEffect(() => {
    setSettingsOpen(false);
    setError("");
  }, [requestedId]);

  function openWorkspace(id: string, nextView: DeviceWorkspaceView) {
    setError("");
    setSettingsOpen(false);
    navigate(deviceWorkspaceUrl(id, nextView));
  }
  function onChanged(next: Device) {
    setDevices((current) =>
      current.map((item) => (item.device_id === next.device_id ? next : item)),
    );
    setError("");
  }
  function onOperation(next: DeviceOperation) {
    setOperations((current) =>
      [
        next,
        ...current.filter((item) => item.operation_id !== next.operation_id),
      ].slice(0, 100),
    );
    setError("");
    if (next.status === "pending_confirmation") setLedgerOpen(true);
  }
  const visibleOperations = inWorkspace
    ? operations.filter(
        (operation) =>
          operation.device_id === requestedId ||
          operation.params.target_device_id === requestedId,
      )
    : operations;
  const pendingCount = visibleOperations.filter(
    (operation) => operation.status === "pending_confirmation",
  ).length;
  const base = new URL(getApiUrl(""), window.location.href);
  const serverUrl = `${base.origin}${base.pathname.replace(/\/api\/?$/, "")}`;
  const validPairing = pairing && pairing.expires_at * 1000 > now;
  const pairingCommand = validPairing
    ? `octop device connect --server "${serverUrl}" --pair-code "${pairing.pairing_code}" --name "My device" --share "PATH"`
    : "";
  async function copy(value: string) {
    if (await copyText(value)) message.success(t("devices.copied"));
    else message.error(t("devices.copyFailed"));
  }
  function status(item: Device) {
    return t(
      item.revoked_at !== null
        ? "devices.revoked"
        : item.online
        ? "devices.online"
        : "devices.offline",
    );
  }
  const views = [
    { key: "desktop" as const, icon: Monitor, label: t("devices.desktopTab") },
    { key: "files" as const, icon: File, label: t("devices.filesTab") },
    { key: "command" as const, icon: Terminal, label: t("devices.commandTab") },
  ];
  const hostTools = [
    {
      permission: "terminal",
      path: "/workbench/terminal",
      icon: Terminal,
      label: t("devices.hostTerminal", "本机终端"),
    },
    {
      permission: "browser",
      path: "/workbench/browser",
      icon: Globe,
      label: t("devices.hostBrowser", "本机浏览器"),
    },
    {
      permission: "desktop",
      path: "/remote-desktop/desktop",
      icon: Monitor,
      label: t("devices.hostDesktop", "本机桌面"),
    },
    ...(mobileEnabled
      ? [
          {
            permission: "mobile",
            path: "/remote-desktop/phone",
            icon: Smartphone,
            label: t("devices.hostPhone", "USB 手机"),
          },
        ]
      : []),
  ].filter((tool) => userCan(user, tool.permission));

  return (
    <PageShell
      title={
        inWorkspace
          ? t("devices.workspaceTitle", "设备工作区")
          : t("devices.title")
      }
      subtitle={
        inWorkspace
          ? undefined
          : t(
              "devices.managerSubtitle",
              "管理连接与授权；桌面、文件和命令在独立工作区操作。",
            )
      }
      actions={
        <div className="devices-actions">
          <Button
            icon={<History size={16} />}
            onClick={() => setLedgerOpen(true)}
          >
            {t("devices.records", "操作记录")}
            {pendingCount ? ` (${pendingCount})` : ""}
          </Button>
          {!inWorkspace && (
            <>
              <AccessKeys />
              <Button
                icon={<RefreshCw size={16} />}
                loading={loading}
                onClick={() => void refresh()}
              >
                {t("devices.refresh")}
              </Button>
              <Button
                type="primary"
                icon={<Link2 size={16} />}
                onClick={() => {
                  setNow(Date.now());
                  setPairingOpen(true);
                }}
              >
                {t("devices.addDevice")}
              </Button>
            </>
          )}
        </div>
      }
    >
      <div
        className={`devices-page ${
          inWorkspace ? "devices-workspace" : "devices-management"
        }`}
      >
        {error && (
          <Alert
            type="error"
            showIcon
            closable
            message={error}
            onClose={() => setError("")}
          />
        )}
        {inWorkspace ? (
          <>
            <div className="devices-workspace-bar">
              <Button
                icon={<ArrowLeft size={16} />}
                onClick={() => setQuery({})}
              >
                {t("devices.backToDevices", "返回设备")}
              </Button>
              <Select
                className="devices-workspace-target"
                aria-label={t("devices.targetDevice")}
                value={requestedId}
                onChange={(id) => openWorkspace(id, view!)}
                options={devices.map((item) => ({
                  value: item.device_id,
                  label: `${item.name} · ${status(item)}`,
                }))}
              />
              {device && (
                <>
                  <Tag
                    color={
                      device.online && device.revoked_at === null
                        ? "green"
                        : "orange"
                    }
                  >
                    {status(device)}
                  </Tag>
                  <span className="devices-workspace-platform">
                    {device.platform}
                  </span>
                  <Button
                    icon={<Shield size={16} />}
                    onClick={() => setSettingsOpen(true)}
                  >
                    {t("devices.settingsTab")}
                  </Button>
                </>
              )}
            </div>
            {device ? (
              <>
                <Segmented
                  aria-label={t("devices.workspaceTools", "设备操作")}
                  value={view}
                  onChange={(value) =>
                    openWorkspace(
                      device.device_id,
                      value as DeviceWorkspaceView,
                    )
                  }
                  options={views.map(({ key, icon: Icon, label }) => ({
                    value: key,
                    label: (
                      <span className="devices-tab">
                        <Icon size={16} />
                        {label}
                      </span>
                    ),
                    disabled: !supportsWorkspaceView(device, key),
                  }))}
                />
                {(!device.online || device.revoked_at !== null) && (
                  <Alert
                    type="warning"
                    showIcon
                    message={t(
                      "devices.unavailableWorkspace",
                      "设备当前不可用。客户端重新连接后可继续操作；不会自动重放之前的动作。",
                    )}
                  />
                )}
                <section
                  className={`devices-workspace-body devices-workspace-${view}`}
                  aria-label={t("devices.workspaceContent", "操作区")}
                >
                  {!supportsWorkspaceView(device, view!) ? (
                    <Alert
                      type="info"
                      showIcon
                      message={t(
                        "devices.unavailableTool",
                        "这台设备未授权或不支持此能力。Linux 无桌面客户端请使用文件或命令。",
                      )}
                    />
                  ) : view === "desktop" ? (
                    <DeviceDesktop
                      key={device.device_id}
                      device={device}
                      onError={onError}
                    />
                  ) : view === "files" ? (
                    <DeviceFiles
                      key={device.device_id}
                      device={device}
                      devices={devices}
                      onError={onError}
                      onOperation={onOperation}
                    />
                  ) : (
                    <DeviceCommand
                      key={device.device_id}
                      device={device}
                      onError={onError}
                      onOperation={onOperation}
                    />
                  )}
                </section>
              </>
            ) : (
              loaded && (
                <Empty
                  description={t(
                    "devices.targetMissing",
                    "此目标不存在或不属于当前账号，请返回设备列表。",
                  )}
                />
              )
            )}
          </>
        ) : (
          <>
            <div className="devices-management-heading">
              <h2>
                {t("devices.myDevices")} <small>{devices.length}</small>
              </h2>
              <p className="devices-muted">{t("devices.mobileHint")}</p>
            </div>
            {!devices.length && !loading && (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("devices.noDevices")}
              />
            )}
            <div className="devices-card-grid">
              {devices.map((item) => (
                <article className="devices-device-card" key={item.device_id}>
                  <div className="devices-card-heading">
                    <div className="devices-card-icon">
                      {item.platform.toLowerCase().includes("linux") ? (
                        <Terminal size={22} />
                      ) : (
                        <Laptop size={22} />
                      )}
                    </div>
                    <div>
                      <h2>{item.name}</h2>
                      <span className="devices-muted">{item.platform}</span>
                    </div>
                    <Tag
                      color={
                        item.revoked_at !== null
                          ? "default"
                          : item.online
                          ? "green"
                          : "orange"
                      }
                    >
                      {status(item)}
                    </Tag>
                  </div>
                  <p className="devices-path">
                    {t("devices.lastSeen")}:{" "}
                    {item.last_seen_at
                      ? formatServerDateTime(item.last_seen_at, serverTimezone)
                      : t("devices.neverSeen")}
                  </p>
                  <div className="devices-roster-grants">
                    {item.permissions.map((permission) => (
                      <Tag key={permission}>
                        {t(`devices.permissions.${permission}`, {
                          defaultValue: permission,
                        })}
                      </Tag>
                    ))}
                  </div>
                  <div className="devices-card-actions">
                    {views
                      .filter(({ key }) => supportsWorkspaceView(item, key))
                      .map(({ key, icon: Icon, label }) => (
                        <Button
                          key={key}
                          icon={<Icon size={16} />}
                          onClick={() => openWorkspace(item.device_id, key)}
                        >
                          {label}
                        </Button>
                      ))}
                    <Button
                      icon={<Shield size={16} />}
                      onClick={() => {
                        setSelected(item.device_id);
                        setSettingsOpen(true);
                      }}
                    >
                      {t("devices.settingsTab")}
                    </Button>
                  </div>
                </article>
              ))}
            </div>
            {hostTools.length > 0 && (
              <section className="devices-host-tools">
                <h2>{t("devices.hostTools", "当前管理端的本机工具")}</h2>
                <p className="devices-muted">
                  {t(
                    "devices.hostToolsHint",
                    "以下入口操作运行 Octop 的当前宿主；上方设备工作区操作所选远程设备。",
                  )}
                </p>
                <div className="devices-actions">
                  {hostTools.map(({ path, icon: Icon, label }) => (
                    <Button
                      key={path}
                      icon={<Icon size={16} />}
                      onClick={() => navigate(path)}
                    >
                      {label}
                    </Button>
                  ))}
                </div>
              </section>
            )}
            {base.protocol === "http:" && (
              <Alert
                type="warning"
                showIcon
                message={t(
                  "devices.httpWarning",
                  "当前连接使用 HTTP，内容未加密。跨网络部署请使用受信任的 HTTPS 或 VPN；不要在公共网络传递配对码和密钥。",
                )}
              />
            )}
          </>
        )}
      </div>
      <Drawer
        title={
          device
            ? `${device.name} · ${t("devices.settingsTab")}`
            : t("devices.settingsTab")
        }
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        width={480}
        rootClassName="devices-drawer"
      >
        {device && (
          <DeviceSettings
            key={`${device.device_id}:${device.grant_version}`}
            device={device}
            onChanged={onChanged}
            onError={onError}
          />
        )}
      </Drawer>
      <Drawer
        title={
          inWorkspace && device
            ? `${device.name} · ${t("devices.records", "操作记录")}`
            : t("devices.records", "操作记录")
        }
        open={ledgerOpen}
        onClose={() => setLedgerOpen(false)}
        width={520}
        rootClassName="devices-drawer"
      >
        <aside className="devices-ledger" aria-label={t("devices.ledger")}>
          <h2>{t("devices.ledger")}</h2>
          <p className="devices-muted">{t("devices.ledgerHint")}</p>
          {!visibleOperations.length && (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("devices.noOperations")}
            />
          )}
          {visibleOperations.map((operation) => {
            const name =
              devices.find((item) => item.device_id === operation.device_id)
                ?.name ?? operation.device_id;
            const result = operation.result;
            const total =
              typeof result?.bytes_total === "number" ? result.bytes_total : 0;
            const done =
              typeof result?.bytes_done === "number" ? result.bytes_done : 0;
            const targetName =
              typeof operation.params.target_device_id === "string"
                ? devices.find(
                    (item) =>
                      item.device_id === operation.params.target_device_id,
                  )?.name ?? operation.params.target_device_id
                : "";
            return (
              <article
                className="devices-operation"
                key={operation.operation_id}
              >
                <div>
                  <strong>
                    {name}
                    {targetName ? ` → ${targetName}` : ""}
                  </strong>
                  <Tag
                    color={
                      operation.status === "completed"
                        ? "green"
                        : operation.status === "failed"
                        ? "red"
                        : operation.status === "unknown"
                        ? "orange"
                        : "default"
                    }
                  >
                    {t(`devices.status.${operation.status}`)}
                  </Tag>
                </div>
                <code>{operation.action}</code>
                <small>
                  {formatServerDateTime(operation.created_at, serverTimezone)} ·{" "}
                  {operation.agent_id ?? t("devices.you")}
                </small>
                {operation.action === "command.run" && (
                  <pre>{JSON.stringify(operation.params.argv)}</pre>
                )}
                {operation.action === "files.transfer" && (
                  <p className="devices-path">
                    {String(operation.params.source_path ?? "")} →{" "}
                    {String(operation.params.target_path ?? "")}
                  </p>
                )}
                {total > 0 && (
                  <>
                    <small>
                      {formatBytes(done)} / {formatBytes(total)}
                    </small>
                    <Progress
                      percent={
                        operation.status === "completed"
                          ? 100
                          : Math.min(99, Math.floor((done / total) * 100))
                      }
                      status={
                        operation.status === "completed"
                          ? "success"
                          : operation.status === "failed" ||
                            operation.status === "cancelled"
                          ? "exception"
                          : "normal"
                      }
                    />
                  </>
                )}
                {operation.error && (
                  <p className="devices-operation-error">{operation.error}</p>
                )}
                {result && (
                  <details>
                    <summary>{t("devices.operationResult")}</summary>
                    <pre>{JSON.stringify(result, null, 2)}</pre>
                  </details>
                )}
                {operation.status === "unknown" && (
                  <p className="devices-muted">{t("devices.unknownHint")}</p>
                )}
                <div className="devices-actions">
                  {operation.status === "pending_confirmation" && (
                    <Button
                      type="primary"
                      loading={operationBusy === operation.operation_id}
                      onClick={() =>
                        modal.confirm({
                          title: t("devices.confirmCommand", { name }),
                          content: (
                            <div>
                              <p>{t("devices.confirmCommandHint")}</p>
                              <pre className="devices-confirm-argv">
                                {JSON.stringify(operation.params.argv, null, 2)}
                              </pre>
                            </div>
                          ),
                          okText: t("devices.confirmRun"),
                          cancelText: t("common.cancel"),
                          onOk: async () => {
                            setOperationBusy(operation.operation_id);
                            try {
                              onOperation(
                                await devicesApi.confirm(
                                  operation.operation_id,
                                ),
                              );
                            } catch (err) {
                              onError(err);
                              throw err;
                            } finally {
                              setOperationBusy("");
                            }
                          },
                        })
                      }
                    >
                      {t("devices.confirmRun")}
                    </Button>
                  )}
                  {["pending_confirmation", "queued", "running"].includes(
                    operation.status,
                  ) && (
                    <Button
                      loading={operationBusy === operation.operation_id}
                      onClick={async () => {
                        setOperationBusy(operation.operation_id);
                        try {
                          onOperation(
                            await devicesApi.cancel(operation.operation_id),
                          );
                        } catch (err) {
                          onError(err);
                        } finally {
                          setOperationBusy("");
                        }
                      }}
                    >
                      {t("devices.cancelOperation")}
                    </Button>
                  )}
                </div>
              </article>
            );
          })}
        </aside>
      </Drawer>
      <Modal
        title={t("devices.pairingTitle")}
        open={pairingOpen}
        onCancel={() => {
          setPairingOpen(false);
          setPairing(null);
        }}
        footer={null}
      >
        <div className="devices-tool devices-pairing">
          <p>{t("devices.pairingHint")}</p>
          <Alert
            type="info"
            showIcon
            message={t(
              "devices.guidedSetup",
              "便携包运行 setup-device.bat（Linux 为 setup-device.sh）即可按提示加入；以后双击 start-device.bat 或运行 start-device.sh，恢复全部已保存连接。新增管理端需要单独授权。各管理端的聊天、项目和记录分别保存。",
            )}
          />
          {!validPairing && (
            <Button
              type="primary"
              loading={pairingBusy}
              onClick={async () => {
                setPairingBusy(true);
                try {
                  setPairing(await devicesApi.pairing());
                  setNow(Date.now());
                } catch (err) {
                  onError(err);
                } finally {
                  setPairingBusy(false);
                }
              }}
            >
              {t("devices.generatePairing")}
            </Button>
          )}
          {validPairing && (
            <>
              <code className="devices-pairing-code">
                {pairing.pairing_code}
              </code>
              <p>
                {t("devices.pairingExpiry", {
                  time: formatServerDateTime(
                    pairing.expires_at,
                    serverTimezone,
                  ),
                })}
              </p>
              <Button
                icon={<Copy size={16} />}
                onClick={() => void copy(pairing.pairing_code)}
              >
                {t("devices.copyCode")}
              </Button>
              <p>{t("devices.cliHint")}</p>
              <pre>{pairingCommand}</pre>
              <Button
                icon={<Copy size={16} />}
                onClick={() => void copy(pairingCommand)}
              >
                {t("devices.copyCommand")}
              </Button>
            </>
          )}
          <p className="devices-muted">{t("devices.cliPermissions")}</p>
          <p className="devices-muted">{t("devices.pairingPrivacy")}</p>
          {base.protocol === "http:" && (
            <Alert
              type="warning"
              showIcon
              message={t(
                "devices.httpWarning",
                "当前连接使用 HTTP，内容未加密。跨网络部署请使用受信任的 HTTPS 或 VPN；不要在公共网络传递配对码和密钥。",
              )}
            />
          )}
        </div>
      </Modal>
    </PageShell>
  );
}
