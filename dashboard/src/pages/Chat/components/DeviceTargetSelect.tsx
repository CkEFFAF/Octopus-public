import { useEffect, useState } from "react";
import { Select } from "antd";
import { useTranslation } from "react-i18next";
import { devicesApi, type Device } from "../../../api/modules/devices";

import {
  getSelectedDeviceId,
  setSelectedDeviceId,
} from "../hooks/deviceTarget";
import styles from "../index.module.less";

export default function DeviceTargetSelect() {
  const { t } = useTranslation();
  const [devices, setDevices] = useState<Device[]>([]);
  const [selected, setSelected] = useState(getSelectedDeviceId());
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let disposed = false;
    setSelectedDeviceId("");
    setSelected("");
    const refresh = async () => {
      try {
        const response = await devicesApi.list();
        if (disposed) return;
        setDevices(response.devices);
        setFailed(false);
        if (
          getSelectedDeviceId() &&
          !response.devices.some(
            (d) =>
              d.device_id === getSelectedDeviceId() && d.revoked_at === null,
          )
        ) {
          setSelectedDeviceId("");
          setSelected("");
        }
      } catch {
        if (!disposed) setFailed(true);
      }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 15000);
    return () => {
      disposed = true;
      clearInterval(timer);
      setSelectedDeviceId("");
    };
  }, []);
  const availableDevices = devices.filter(
    (device) => device.revoked_at === null,
  );
  if (!failed && availableDevices.length === 0) return null;

  return (
    <div className={styles.deviceTargetSelect}>
      <Select
        aria-label={t("devices.targetDevice")}
        size="small"
        value={selected || undefined}
        allowClear
        placeholder={failed ? t("devices.loadFailed") : t("devices.noTarget")}
        className={styles.deviceTargetPicker}
        options={availableDevices.map((d) => ({
          value: d.device_id,
          label: `${d.name} · ${t(
            d.online ? "devices.online" : "devices.offline",
          )}`,
          disabled: !d.online,
        }))}
        onChange={(value) => {
          setSelectedDeviceId(value || "");
          setSelected(value || "");
        }}
      />
      <a href="/devices" className={styles.deviceTargetManage}>
        {t("devices.manageDevices")}
      </a>
    </div>
  );
}
