import { useEffect, useRef, useState } from "react";
import { Alert, App, Button, Input, Modal, Select, Tag } from "antd";
import { Monitor, ChevronDown, Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { devicesApi, type Device } from "../../../api/modules/devices";

import {
  getExecutionSelection,
  getExecutionWorkModeRevision,
  executionScope,
  useExecutionSelection,
  setExecutionSelection,
  LOCAL_TARGET,
  targetOption,
  executionSelectionReady,
  setExecutionSelectionStatus,
  useExecutionSelectionStatus,
} from "../hooks/deviceTarget";
import styles from "../index.module.less";
import DeviceAccessRequest from "../../Devices/DeviceAccessRequest";
import { executionApi } from "../../../api/modules/execution";

export default function DeviceTargetSelect({
  agentId,
  threadId,
  defaultDeviceId,
}: {
  agentId?: string | null;
  threadId?: string | null;
  defaultDeviceId?: string;
}) {
  const { t } = useTranslation();
  const [devices, setDevices] = useState<Device[]>([]);
  const scope = executionScope(agentId, threadId);
  const hydrationBaseline = useRef({
    scope,
    selection: getExecutionSelection(scope),
    workModeRevision: getExecutionWorkModeRevision(scope),
  });
  if (hydrationBaseline.current.scope !== scope)
    hydrationBaseline.current = {
      scope,
      selection: getExecutionSelection(scope),
      workModeRevision: getExecutionWorkModeRevision(scope),
    };
  const { deviceId, workingDir } = useExecutionSelection(scope);
  const selectionStatus = useExecutionSelectionStatus(scope);
  const selectionReady = executionSelectionReady(scope, threadId);
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const [accountDefault, setAccountDefault] = useState<string | null>(null);
  const [savingDefault, setSavingDefault] = useState(false);
  const [localAvailable, setLocalAvailable] = useState(false);
  const selected = selectionReady
    ? deviceId || defaultDeviceId || accountDefault || ""
    : "";
  const [pendingTarget, setPendingTarget] = useState<string | null>(null);
  const shownTarget = pendingTarget ?? selected;
  const isLocal = shownTarget === LOCAL_TARGET;
  const [directory, setDirectory] = useState(workingDir ?? "");
  const [savingSelection, setSavingSelection] = useState(false);
  const [selectionError, setSelectionError] = useState(false);
  const activeScope = useRef(scope);
  activeScope.current = scope;
  const changeVersion = useRef(0);
  const saveQueue = useRef<Promise<unknown>>(Promise.resolve());
  const mounted = useRef(true);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const { message } = App.useApp();
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    changeVersion.current += 1;
    setPendingTarget(null);
    setSavingSelection(false);
    setSelectionError(false);
    setOpen(false);
  }, [scope]);
  useEffect(() => {
    setDirectory(workingDir ?? "");
  }, [scope, deviceId, workingDir]);
  useEffect(() => {
    let disposed = false;
    void executionApi
      .defaultTarget()
      .then((value) => {
        if (!disposed) setAccountDefault(targetOption(value) || null);
      })
      .catch(() => {
        if (!disposed) setFailed(true);
      });
    void executionApi
      .localAvailable()
      .then((value) => {
        if (!disposed) setLocalAvailable(value.available);
      })
      .catch(() => {
        if (!disposed) setLocalAvailable(false);
      });
    return () => {
      disposed = true;
    };
  }, [open]);
  useEffect(() => {
    if (!threadId || threadId.startsWith("__")) return;
    let disposed = false;
    const before = hydrationBaseline.current.selection;
    const workModeRevision = hydrationBaseline.current.workModeRevision;
    const version = changeVersion.current;
    setExecutionSelectionStatus(scope, "loading");
    void devicesApi
      .executionSelection(threadId)
      .then((value) => {
        if (!disposed && changeVersion.current === version) {
          const current = getExecutionSelection(scope);
          setExecutionSelection(scope, {
            ...(current.deviceId === before.deviceId
              ? { deviceId: targetOption(value) }
              : {}),
            ...(current.workingDir === before.workingDir
              ? { workingDir: value.working_dir ?? undefined }
              : {}),
            ...(getExecutionWorkModeRevision(scope) === workModeRevision
              ? { workMode: value.work_mode }
              : {}),
          });
          setExecutionSelectionStatus(scope, "ready");
        }
      })
      .catch(() => {
        if (!disposed) setExecutionSelectionStatus(scope, "error");
      });
    return () => {
      disposed = true;
      setExecutionSelectionStatus(scope, "unknown");
    };
  }, [scope, threadId, restoreAttempt]);
  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      try {
        const response = await devicesApi.list();
        if (disposed) return;
        setDevices(response.devices);
        setFailed(false);
      } catch {
        if (!disposed) setFailed(true);
      }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 15000);
    return () => {
      disposed = true;
      clearInterval(timer);
    };
  }, [scope]);
  const availableDevices = devices.filter(
    (device) => device.revoked_at === null,
  );
  const target = availableDevices.find((d) => d.device_id === shownTarget);
  const committedTarget = availableDevices.find(
    (d) => d.device_id === selected,
  );

  const saveSelection = (option: string, nextDirectory: string | null) => {
    if (!selectionReady) return;
    const version = ++changeVersion.current;
    setSelectionError(false);
    setDirectory(nextDirectory ?? "");
    if (!threadId || threadId.startsWith("__")) {
      setExecutionSelection(scope, {
        deviceId: option,
        workingDir: nextDirectory ?? undefined,
      });
      return;
    }
    setPendingTarget(option);
    setSavingSelection(true);
    const current = () =>
      mounted.current &&
      activeScope.current === scope &&
      changeVersion.current === version;
    // Serialize writes so rapid target changes cannot persist out of order.
    const saving = saveQueue.current
      .catch(() => undefined)
      .then(() =>
        devicesApi.saveExecutionSelection(threadId, {
          target_kind: option === LOCAL_TARGET ? "local" : "device",
          device_id: option && option !== LOCAL_TARGET ? option : null,
          working_dir: nextDirectory,
        }),
      );
    saveQueue.current = saving;
    void saving
      .then((value) => {
        if (!current()) return;
        setExecutionSelection(scope, {
          deviceId: targetOption(value),
          workingDir: value.working_dir ?? undefined,
        });
      })
      .catch(() => {
        if (!current()) return;
        setSelectionError(true);
        if (option !== selected)
          setDirectory(getExecutionSelection(scope).workingDir ?? "");
      })
      .finally(() => {
        if (!current()) return;
        setPendingTarget(null);
        setSavingSelection(false);
      });
  };

  return (
    <>
      <button
        type="button"
        className={styles.deviceTargetButton}
        onClick={() => setOpen(true)}
        aria-label={t("devices.targetDevice")}
      >
        <Monitor size={15} />
        <span>
          {!selectionReady
            ? t(
                selectionStatus === "error"
                  ? "devices.sessionSelectionFailed"
                  : "devices.sessionSelectionLoading",
              )
            : (selected === LOCAL_TARGET
                ? t("devices.localExecution")
                : committedTarget?.name) ??
              (selected
                ? t("devices.targetUnavailable")
                : t("devices.noTarget"))}
        </span>
        <ChevronDown size={12} />
      </button>
      <Modal
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        title={t("devices.executionTarget")}
        width={520}
        destroyOnHidden
      >
        <p className={styles.deviceTargetSummary}>{t("devices.targetHint")}</p>
        <Select
          aria-label={t("devices.targetDevice")}
          size="small"
          value={shownTarget || undefined}
          loading={
            savingSelection || (!selectionReady && selectionStatus !== "error")
          }
          disabled={!selectionReady}
          allowClear
          placeholder={failed ? t("devices.loadFailed") : t("devices.noTarget")}
          className={styles.deviceTargetPicker}
          options={[
            ...(localAvailable
              ? [{ value: LOCAL_TARGET, label: t("devices.localExecution") }]
              : []),
            ...availableDevices.map((d) => ({
              value: d.device_id,
              label: `${d.name} · ${t(
                d.online ? "devices.online" : "devices.offline",
              )}`,
              disabled: !d.online,
            })),
            ...(shownTarget && !target && !isLocal
              ? [
                  {
                    value: shownTarget,
                    label: t("devices.targetUnavailable"),
                    disabled: true,
                  },
                ]
              : []),
          ]}
          onChange={(value) => {
            saveSelection(value || "", null);
          }}
        />
        {!selectionReady && (
          <Alert
            type={selectionStatus === "error" ? "error" : "info"}
            showIcon
            message={t(
              selectionStatus === "error"
                ? "devices.sessionSelectionFailed"
                : "devices.sessionSelectionLoading",
            )}
            action={
              selectionStatus === "error" ? (
                <Button
                  size="small"
                  onClick={() => setRestoreAttempt((attempt) => attempt + 1)}
                >
                  {t("devices.retrySessionSelection")}
                </Button>
              ) : undefined
            }
          />
        )}
        {selectionError && (
          <Alert
            type="error"
            showIcon
            message={t("devices.sessionSaveFailed")}
          />
        )}
        {(isLocal || target?.trust_mode === "owner") && (
          <div className={styles.deviceTargetDetails}>
            <label>
              <strong>{t("devices.sessionWorkingDir")}</strong>
              <Input
                aria-label={t("devices.sessionWorkingDir")}
                size="small"
                value={directory}
                maxLength={4096}
                disabled={!selectionReady || savingSelection}
                placeholder={
                  target?.working_dir ??
                  target?.runtime?.working_dir ??
                  t("devices.sessionWorkingDirPlaceholder")
                }
                onChange={(event) => {
                  if (selectionReady && !savingSelection)
                    setDirectory(event.target.value);
                }}
              />
            </label>
            <Button
              size="small"
              loading={savingSelection}
              disabled={savingSelection || directory === (workingDir ?? "")}
              onClick={() => saveSelection(shownTarget, directory || null)}
            >
              {t("devices.applySessionDirectory")}
            </Button>
            <p className={styles.deviceTargetSummary}>
              {t("devices.sessionWorkingDirHint")}
            </p>
          </div>
        )}
        {isLocal && (
          <p className={styles.deviceTargetSummary}>
            {t("devices.localExecutionHint")}
          </p>
        )}
        {target && (
          <div className={styles.deviceTargetDetails}>
            <div>
              <Tag color={target.online ? "green" : undefined}>
                {t(target.online ? "devices.online" : "devices.offline")}
              </Tag>
              {target.permissions.map((p) => (
                <Tag key={p}>{t(`devices.permissions.${p}`)}</Tag>
              ))}
            </div>
            {target.trust_mode === "owner" ? (
              <>
                <p>{t("devices.trust.ownerHint")}</p>
                <div className={styles.deviceTargetRoot}>
                  <strong>{t("devices.trust.workingDir")}</strong>
                  <code>
                    {target.working_dir ?? target.runtime?.working_dir ?? "—"}
                  </code>
                </div>
                {target.policy_revision !== target.applied_policy_revision && (
                  <Tag color="orange">{t("devices.trust.pending")}</Tag>
                )}
              </>
            ) : (
              <>
                {target.roots.map((r) => (
                  <div className={styles.deviceTargetRoot} key={r.id}>
                    <strong>{r.name}</strong>
                    <code>{r.path}</code>
                    <small>
                      {t(r.write ? "devices.write" : "devices.read")}
                    </small>
                  </div>
                ))}
                {!target.roots.length && <p>{t("devices.noRoots")}</p>}
                <DeviceAccessRequest
                  device={target}
                  onChanged={(d) =>
                    setDevices((current) =>
                      current.map((item) =>
                        item.device_id === d.device_id ? d : item,
                      ),
                    )
                  }
                  onError={() => void message.error(t("devices.loadFailed"))}
                />
              </>
            )}
          </div>
        )}
        {(target || isLocal) && (
          <Button
            type="text"
            size="small"
            loading={savingDefault}
            disabled={savingSelection || selected === accountDefault}
            onClick={() => {
              setSavingDefault(true);
              void executionApi
                .saveDefaultTarget(
                  isLocal ? null : selected,
                  undefined,
                  isLocal ? "local" : "device",
                )
                .then((value) => {
                  setAccountDefault(targetOption(value) || null);
                  void message.success(t("devices.defaultSaved"));
                })
                .catch(() => void message.error(t("devices.loadFailed")))
                .finally(() => setSavingDefault(false));
            }}
          >
            {t(
              selected === accountDefault
                ? "devices.accountDefault"
                : "devices.setAccountDefault",
            )}
          </Button>
        )}
        {accountDefault && (
          <Button
            type="text"
            size="small"
            loading={savingDefault}
            disabled={savingSelection}
            onClick={() => {
              setSavingDefault(true);
              void executionApi
                .saveDefaultTarget(null)
                .then(() => setAccountDefault(null))
                .catch(() => void message.error(t("devices.loadFailed")))
                .finally(() => setSavingDefault(false));
            }}
          >
            {t("devices.clearAccountDefault")}
          </Button>
        )}
        <Button
          type="link"
          href={
            target
              ? `/devices?device=${encodeURIComponent(target.device_id)}`
              : "/devices"
          }
          icon={<Settings2 size={14} />}
        >
          {t("devices.manageDevices")}
        </Button>
      </Modal>
    </>
  );
}
