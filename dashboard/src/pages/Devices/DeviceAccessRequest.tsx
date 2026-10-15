import { useState } from "react";
import { Alert, Button, Checkbox, Input } from "antd";
import { useTranslation } from "react-i18next";
import { devicesApi, type Device } from "../../api/modules/devices";

export default function DeviceAccessRequest({
  device,
  onChanged,
  onError,
}: {
  device: Device;
  onChanged: (device: Device) => void;
  onError: (error: unknown) => void;
}) {
  const { t } = useTranslation();
  const [path, setPath] = useState("");
  const [write, setWrite] = useState(false);
  const [execute, setExecute] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <div className="devices-access-request">
      <p className="devices-muted">{t("devices.requestAccessHint")}</p>
      <Input
        value={path}
        maxLength={4096}
        placeholder={t("devices.absolutePath")}
        aria-label={t("devices.absolutePath")}
        onChange={(e) => setPath(e.target.value)}
      />
      <div className="devices-actions">
        <Checkbox
          checked={write}
          disabled={!device.capabilities.includes("files_write")}
          onChange={(e) => setWrite(e.target.checked)}
        >
          {t("devices.write")}
        </Checkbox>
        <Checkbox
          checked={execute}
          disabled={!device.capabilities.includes("command_exec")}
          onChange={(e) => setExecute(e.target.checked)}
        >
          {t("devices.permissions.command_exec")}
        </Checkbox>
        <Button
          loading={busy}
          disabled={
            !path.trim() || !device.online || Boolean(device.pending_proposal)
          }
          onClick={async () => {
            setBusy(true);
            try {
              const existing = device.roots.find((r) => r.path === path.trim());
              const permissions = new Set([
                ...device.permissions,
                "files_read",
              ]);
              if (write) permissions.add("files_write");
              if (execute) permissions.add("command_exec");
              onChanged(
                await devicesApi.requestAccess(device.device_id, {
                  permissions: [...permissions],
                  roots: [
                    ...device.roots.filter((r) => r.path !== path.trim()),
                    {
                      id:
                        existing?.id ??
                        `requested-${Date.now().toString(36)}-${Math.random()
                          .toString(36)
                          .slice(2, 10)}`,
                      name: existing?.name ?? "Workspace",
                      path: path.trim(),
                      read: true,
                      write: write || Boolean(existing?.write),
                    },
                  ],
                }),
              );
              setPath("");
            } catch (error) {
              onError(error);
            } finally {
              setBusy(false);
            }
          }}
        >
          {t("devices.requestAccess")}
        </Button>
      </div>
      {device.pending_proposal && (
        <Alert
          type="info"
          showIcon
          message={t("devices.pendingGrant")}
          description={
            <div>
              {device.pending_proposal.roots.map((r) => (
                <div key={r.id}>{r.path}</div>
              ))}
              <small>{t("devices.headlessApprovalHint")}</small>
            </div>
          }
        />
      )}
    </div>
  );
}
