import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Spin, Tag } from "antd";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  devicesApi,
  type Device,
  type DeviceStatus,
} from "../../api/modules/devices";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../utils/formatMessageTime";
import DeviceCapabilities from "./DeviceCapabilities";
import DeviceCapabilityPolicyPanel from "./DeviceCapabilityPolicy";

export default function DeviceDetails({
  device,
  onDeviceUpdated,
}: {
  device: Device;
  onDeviceUpdated?: (device: Device) => void;
}) {
  const { t } = useTranslation();
  const timezone = useServerTimezone();
  const [status, setStatus] = useState<DeviceStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!device.online || device.revoked_at !== null) {
        setStatus(null);
        setError(false);
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(false);
      setStatus(null);
      try {
        setStatus(
          await devicesApi.call(device.device_id, "status", {}, signal),
        );
      } catch {
        if (!signal?.aborted) setError(true);
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [device.device_id, device.online, device.revoked_at],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const rows = [
    [t("devices.deviceName"), device.name],
    [t("devices.platformLabel"), device.platform],
    [t("devices.deviceId"), device.device_id],
    [
      t("devices.connectionStatus"),
      t(
        device.revoked_at !== null
          ? "devices.revoked"
          : device.online
          ? "devices.online"
          : "devices.offline",
      ),
    ],
    [
      t("devices.lastSeen"),
      device.last_seen_at
        ? formatServerDateTime(device.last_seen_at, timezone)
        : t("devices.neverSeen"),
    ],
  ];
  const systemRows = [
    [t("devices.hostname"), status?.hostname],
    [t("devices.osVersion"), status?.system?.os_version],
    [t("devices.architecture"), status?.system?.architecture],
    [t("devices.cpu"), status?.system?.cpu],
    [t("devices.mainboard"), status?.system?.mainboard],
  ];

  return (
    <div className="devices-detail">
      <h3>{t("devices.registrationInfo")}</h3>
      <dl className="devices-detail-list">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <h3>{t("devices.systemInfo")}</h3>
      {device.online && device.revoked_at === null ? (
        <Button
          size="small"
          icon={<RefreshCw size={14} />}
          onClick={() => void load()}
          loading={loading}
        >
          {t("devices.refresh")}
        </Button>
      ) : (
        <Alert type="info" showIcon message={t("devices.detailsOffline")} />
      )}
      {loading && !status && <Spin />}
      {error && (
        <Alert type="warning" showIcon message={t("devices.detailsFailed")} />
      )}
      {status && !status.system && (
        <Alert
          type="info"
          showIcon
          message={t("devices.clientUpdateRequired")}
        />
      )}
      {status && (
        <dl className="devices-detail-list">
          {systemRows.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>
                {value ||
                  t(
                    status.system
                      ? "devices.systemUnavailable"
                      : "devices.notReported",
                  )}
              </dd>
            </div>
          ))}
        </dl>
      )}
      <h3>{t("devices.availableCapabilities")}</h3>
      <div className="devices-detail-tags">
        {device.capabilities.length
          ? device.capabilities.map((value) => (
              <Tag key={value}>
                {t(`devices.permissions.${value}`, { defaultValue: value })}
              </Tag>
            ))
          : t("devices.none")}
      </div>
      <h3>{t("devices.permissionsTitle")}</h3>
      <div className="devices-detail-tags">
        {device.permissions.length
          ? device.permissions.map((value) => (
              <Tag key={value} color="blue">
                {t(`devices.permissions.${value}`, { defaultValue: value })}
              </Tag>
            ))
          : t("devices.none")}
      </div>
      <DeviceCapabilities device={device} />
      <DeviceCapabilityPolicyPanel
        device={device}
        onSaved={onDeviceUpdated}
      />
      <h3>
        {t(
          device.trust_mode === "owner"
            ? "devices.trust.title"
            : "devices.sharedRoots",
        )}
      </h3>
      <dl className="devices-detail-list">
        <div>
          <dt>{t("devices.trust.desired")}</dt>
          <dd>
            {t(
              device.trust_mode === "owner"
                ? "devices.trust.owner"
                : "devices.trust.restricted",
            )}
          </dd>
        </div>
        <div>
          <dt>{t("devices.trust.applied")}</dt>
          <dd>
            {device.applied_trust_mode
              ? t(`devices.trust.${device.applied_trust_mode}`)
              : t("devices.notReported")}
          </dd>
        </div>
        <div>
          <dt>{t("devices.trust.revision")}</dt>
          <dd>
            {device.policy_revision ?? "—"} /{" "}
            {device.applied_policy_revision ?? "—"}
          </dd>
        </div>
        <div>
          <dt>{t("devices.trust.osUser")}</dt>
          <dd>{device.runtime?.os_user ?? t("devices.notReported")}</dd>
        </div>
        <div>
          <dt>{t("devices.trust.protocol")}</dt>
          <dd>
            {device.runtime?.client_protocol_version ??
              t("devices.notReported")}
          </dd>
        </div>
      </dl>
      {device.trust_mode === "owner" ? (
        <>
          <p>{t("devices.trust.ownerHint")}</p>
          <div className="devices-detail-root">
            <strong>{t("devices.trust.workingDir")}</strong>
            <code>
              {device.working_dir ??
                device.runtime?.working_dir ??
                t("devices.notReported")}
            </code>
          </div>
        </>
      ) : device.roots.length ? (
        device.roots.map((root) => (
          <div className="devices-detail-root" key={root.id}>
            <strong>{root.name}</strong>
            <code>{root.path}</code>
            <span>
              {root.read ? t("devices.read") : ""}
              {root.read && root.write ? " · " : ""}
              {root.write ? t("devices.write") : ""}
            </span>
          </div>
        ))
      ) : (
        <p className="devices-muted">{t("devices.noRoots")}</p>
      )}
    </div>
  );
}
