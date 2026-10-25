import { useEffect, useRef, useState } from "react";
import { Alert, Button, Collapse, Table, Tag } from "antd";
import { Radar } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Device } from "../../api/modules/devices";
import type { CapabilityCatalog } from "../../api/modules/externalSources";
import { executionApi } from "../../api/modules/execution";

export default function DeviceCapabilities({ device }: { device: Device }) {
  const { t } = useTranslation();
  const [catalog, setCatalog] = useState<CapabilityCatalog | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = useRef(0);
  useEffect(() => {
    const lifecycleGeneration = active;
    ++lifecycleGeneration.current;
    setCatalog(null);
    setLoading(false);
    setError(null);
    return () => {
      ++lifecycleGeneration.current;
    };
  }, [device.device_id]);
  const discover = async () => {
    const generation = ++active.current;
    setLoading(true);
    setError(null);
    setCatalog(null);
    try {
      const context = await executionApi.createContext({
        device_id: device.device_id,
        work_mode: "ask",
      });
      if (generation !== active.current) return;
      const value = await executionApi.call<CapabilityCatalog>(
        context.context_id,
        "capabilities.discover",
        {},
      );
      if (generation === active.current) setCatalog(value);
    } catch (failure) {
      if (generation === active.current)
        setError(
          failure instanceof Error
            ? failure.message
            : t("skills.external.loadFailed"),
        );
    } finally {
      if (generation === active.current) setLoading(false);
    }
  };
  const supported =
    device.trust_mode === "owner" &&
    device.runtime?.capability_protocol_version === 1;
  return (
    <section>
      <h3>{t("devices.catalog.title")}</h3>
      <p className="devices-muted">{t("devices.catalog.hint")}</p>
      <Button
        size="small"
        icon={<Radar size={14} />}
        loading={loading}
        disabled={!device.online || !supported}
        onClick={() => void discover()}
      >
        {t("skills.external.refresh")}
      </Button>
      {!supported && (
        <p className="devices-muted">{t("devices.catalog.upgrade")}</p>
      )}
      {error && <Alert type="error" showIcon message={error} />}
      {catalog && (
        <>
          <p>
            {device.name} · {catalog.os_user ?? t("devices.notReported")} ·{" "}
            {new Date(catalog.observed_at * 1000).toLocaleString()}
          </p>
          <Table<CapabilityCatalog["entries"][number]>
            size="small"
            rowKey="id"
            dataSource={catalog.entries}
            pagination={{ pageSize: 8, hideOnSinglePage: true }}
            scroll={{ x: 440 }}
            columns={[
              {
                title: t("skills.nameLabel"),
                dataIndex: "name",
                render: (value: string, entry) => (
                  <span title={entry.path ?? undefined}>
                    {value}
                    <br />
                    <small>
                      {entry.source} · {entry.kind}
                    </small>
                  </span>
                ),
              },
              {
                title: t("devices.catalog.version"),
                dataIndex: "version",
                render: (value: string | null) =>
                  value ?? t("devices.catalog.unknown"),
              },
              {
                title: t("devices.connectionStatus"),
                dataIndex: "status",
                render: (value: string, entry) => (
                  <>
                    <Tag>
                      {t(`devices.catalog.${value}`, { defaultValue: value })}
                    </Tag>
                    {entry.dependency_available === false && (
                      <small>{t("devices.catalog.missingDependency")}</small>
                    )}
                  </>
                ),
              },
            ]}
          />
          <Collapse
            ghost
            items={[
              {
                key: "dependencies",
                label: t("devices.catalog.dependencies"),
                children: (
                  <dl className="devices-detail-list">
                    {Object.entries(catalog.dependencies).map(
                      ([name, version]) => (
                        <div key={name}>
                          <dt>{name}</dt>
                          <dd>
                            {version ?? t("devices.catalog.notInstalled")}
                          </dd>
                        </div>
                      ),
                    )}
                  </dl>
                ),
              },
            ]}
          />
        </>
      )}
    </section>
  );
}
