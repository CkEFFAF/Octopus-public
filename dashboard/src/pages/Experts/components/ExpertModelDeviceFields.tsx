import { Form, Input, Select, type FormInstance } from "antd";
import { useTranslation } from "react-i18next";
import type { Device } from "../../../api/modules/devices";
import { useCurrentUser } from "../../../hooks/useCurrentUser";
import { LOCAL_TARGET } from "../../Chat/hooks/deviceTarget";
import {
  buildModelSelectOptions,
  type ModelPickerOption,
} from "../../../utils/modelOptions";

export default function ExpertModelDeviceFields({
  form,
  models,
  modelsLoading,
  devices,
}: {
  form: FormInstance;
  models: ModelPickerOption[];
  modelsLoading: boolean;
  devices: Device[];
}) {
  const { t } = useTranslation();
  const currentUser = useCurrentUser();
  const boundDeviceId = Form.useWatch("device_id", form) as string | undefined;
  return (
    <>
      {" "}
      <Form.Item name="default_model" label={t("experts.defaultModelLabel")}>
        <Select
          loading={modelsLoading}
          placeholder={t("experts.defaultModelPlaceholder")}
          options={buildModelSelectOptions(
            models,
            t("experts.defaultModelAuto"),
          )}
          showSearch
          filterOption={(input, opt) =>
            ((opt?.label as string) ?? "")
              .toLowerCase()
              .includes(input.toLowerCase())
          }
        />
      </Form.Item>
      <Form.Item
        name="device_id"
        label={t("experts.deviceBindingLabel")}
        extra={t("experts.deviceBindingHint")}
      >
        <Select
          allowClear
          placeholder={t("experts.deviceBindingLocal")}
          options={[
            ...(currentUser?.role === "admin"
              ? [
                  {
                    value: LOCAL_TARGET,
                    label: t("devices.localExecution"),
                  },
                ]
              : []),
            ...devices
              .filter((item) => item.revoked_at === null)
              .map((item) => ({
                value: item.device_id,
                label: `${item.name}${
                  item.online ? "" : ` · ${t("devices.offline")}`
                }`,
              })),
          ]}
          onChange={() => {
            form.setFieldValue("device_root_id", undefined);
            form.setFieldValue("device_working_dir", undefined);
          }}
        />
      </Form.Item>
      {boundDeviceId &&
        (boundDeviceId === LOCAL_TARGET ||
          devices.find((item) => item.device_id === boundDeviceId)
            ?.trust_mode === "owner") && (
          <Form.Item
            name="device_working_dir"
            label={t("devices.trust.workingDir")}
            extra={t("devices.trust.ownerHint")}
          >
            <Input
              placeholder={
                devices.find((item) => item.device_id === boundDeviceId)
                  ?.runtime?.working_dir
              }
            />
          </Form.Item>
        )}
      {boundDeviceId &&
        boundDeviceId !== LOCAL_TARGET &&
        devices.find((item) => item.device_id === boundDeviceId)?.trust_mode !==
          "owner" && (
          <Form.Item
            name="device_root_id"
            label={t("experts.deviceRootLabel")}
            rules={[
              {
                required: true,
                message: t("experts.deviceRootRequired"),
              },
            ]}
          >
            <Select
              options={
                devices
                  .find((item) => item.device_id === boundDeviceId)
                  ?.roots.filter((root) => root.read)
                  .map((root) => ({
                    value: root.id,
                    label: `${root.name} · ${root.path}`,
                  })) ?? []
              }
            />
          </Form.Item>
        )}
    </>
  );
}
