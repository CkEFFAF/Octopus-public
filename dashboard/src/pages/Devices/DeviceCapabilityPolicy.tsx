import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Select, Space, Typography, message } from "antd";
import { useTranslation } from "react-i18next";
import {
  devicesApi,
  type Device,
  type DeviceCapabilityPolicy,
} from "../../api/modules/devices";
import { connectorsApi } from "../../api/modules/connectors";

type Props = {
  device: Device;
  onSaved?: (device: Device) => void;
};

export default function DeviceCapabilityPolicyPanel({
  device,
  onSaved,
}: Props) {
  const { t } = useTranslation();
  const [mcpServers, setMcpServers] = useState<string[]>(
    device.capability_policy?.mcp_servers ?? [],
  );
  const [options, setOptions] = useState<{ value: string; label: string }[]>(
    [],
  );
  const [missing, setMissing] = useState<string[]>(
    device.missing_or_unauthorized ?? [],
  );
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const loadOptions = useCallback(async () => {
    try {
      const instances = await connectorsApi.listInstances();
      setOptions(
        instances
          .filter((item) => item.status === "active" && item.mcp_server_name)
          .map((item) => ({
            value: item.mcp_server_name,
            label: item.display_name
              ? `${item.display_name} (${item.mcp_server_name})`
              : item.mcp_server_name,
          })),
      );
    } catch {
      setOptions([]);
    }
  }, []);

  useEffect(() => {
    setMcpServers(device.capability_policy?.mcp_servers ?? []);
    setMissing(device.missing_or_unauthorized ?? []);
    setDirty(false);
  }, [
    device.device_id,
    device.capability_policy,
    device.missing_or_unauthorized,
  ]);

  useEffect(() => {
    void loadOptions();
  }, [loadOptions]);

  const selectOptions = useMemo(() => {
    const known = new Set(options.map((o) => o.value));
    const extras = mcpServers
      .filter((name) => !known.has(name))
      .map((name) => ({ value: name, label: name }));
    return [...options, ...extras];
  }, [options, mcpServers]);

  const save = async () => {
    setSaving(true);
    try {
      const policy: DeviceCapabilityPolicy = {
        schema_version: 1,
        mcp_servers: mcpServers,
        skill_package_ids: device.capability_policy?.skill_package_ids ?? [],
        deny_mcp_servers: device.capability_policy?.deny_mcp_servers ?? [],
        deny_skill_package_ids:
          device.capability_policy?.deny_skill_package_ids ?? [],
      };
      const saved = await devicesApi.setCapabilityPolicy(
        device.device_id,
        policy,
      );
      setMissing(saved.missing_or_unauthorized ?? []);
      setDirty(false);
      message.success(t("devices.capabilityPolicy.savedNextTurn"));
      onSaved?.(saved);
    } catch (err) {
      message.error(
        err instanceof Error
          ? err.message
          : t("devices.capabilityPolicy.saveFailed"),
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="devices-capability-policy">
      <h3>{t("devices.capabilityPolicy.title")}</h3>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        {t("devices.capabilityPolicy.hint")}
      </Typography.Paragraph>
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 12 }}
        message={t("devices.capabilityPolicy.defaultOpenWarning")}
      />
      {missing.length > 0 && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message={t("devices.capabilityPolicy.missingTitle")}
          description={t("devices.capabilityPolicy.missingDesc", {
            names: missing.join(", "),
          })}
        />
      )}
      <Select
        mode="tags"
        style={{ width: "100%" }}
        value={mcpServers}
        options={selectOptions}
        placeholder={t("devices.capabilityPolicy.mcpPlaceholder")}
        onChange={(values) => {
          setMcpServers(values);
          setDirty(true);
        }}
        tokenSeparators={[","]}
      />
      <Space style={{ marginTop: 12 }}>
        <Button
          type="primary"
          loading={saving}
          disabled={!dirty}
          onClick={() => void save()}
        >
          {t("devices.capabilityPolicy.save")}
        </Button>
      </Space>
    </div>
  );
}
