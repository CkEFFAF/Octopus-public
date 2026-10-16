import { useEffect, useState } from "react";
import { Alert, App, Button, Form, Space, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../../../api/request";
import { devicesApi, type Device } from "../../../api/modules/devices";
import type { OctopAgent } from "../../../context/AgentContext";
import { useCurrentUser } from "../../../hooks/useCurrentUser";
import { useAgentFormResources } from "../../../hooks/useAgentFormResources";
import { apiErrorMessage } from "../../../utils/apiError";
import {
  defaultModelFromForm,
  defaultModelToForm,
} from "../../../utils/modelOptions";
import { LOCAL_TARGET, targetOption } from "../../Chat/hooks/deviceTarget";
import ExpertModelDeviceFields from "./ExpertModelDeviceFields";

interface DefaultsValues {
  default_model: string;
  device_id?: string;
  device_root_id?: string;
  device_working_dir?: string;
}

export default function ExpertDefaultsEditor({
  agent,
  onClose,
  onSaved,
  onSavingChange,
  onFullSettings,
}: {
  agent: OctopAgent;
  onClose: () => void;
  onSaved: (updated: OctopAgent) => void;
  onSavingChange: (saving: boolean) => void;
  onFullSettings: () => void;
}) {
  const { t } = useTranslation();
  const { message, modal } = App.useApp();
  const user = useCurrentUser();
  const [form] = Form.useForm<DefaultsValues>();
  const { models, modelsLoading } = useAgentFormResources(true);
  const [detail, setDetail] = useState<OctopAgent | null>(null);
  const [initial, setInitial] = useState<DefaultsValues | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const canEdit =
    Boolean(detail) &&
    !agent.bridge &&
    !detail?.bridge &&
    ((detail?.is_owner ?? agent.is_owner) === true || user?.role === "admin");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDetail(null);
    void Promise.all([
      request<OctopAgent>(`/agents/${agent.agent_id}`),
      devicesApi.list(),
    ])
      .then(([row, response]) => {
        if (cancelled) return;
        const binding = (row.config?.device_binding ?? {}) as {
          target_kind?: string;
          device_id?: string;
          root_id?: string;
          working_dir?: string;
        };
        const values = {
          default_model: defaultModelToForm(row.default_model),
          device_id: targetOption(binding) || undefined,
          device_root_id: binding.root_id,
          device_working_dir: binding.working_dir,
        };
        setDetail(row);
        setDevices(response.devices);
        setInitial(values);
        form.setFieldsValue(values);
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setError(apiErrorMessage(err, t("experts.loadDetailFailed"), t));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agent.agent_id, attempt, form, t]);

  useEffect(() => {
    onSavingChange(saving);
  }, [saving, onSavingChange]);

  const save = async () => {
    if (!canEdit || !detail || !initial || loading || saving) return;
    let values: DefaultsValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {};
      if (values.default_model !== initial.default_model) {
        body.default_model = defaultModelFromForm(values.default_model);
      }
      const bindingChanged =
        values.device_id !== initial.device_id ||
        values.device_root_id !== initial.device_root_id ||
        values.device_working_dir !== initial.device_working_dir;
      if (bindingChanged) {
        // PATCH replaces config: merge the latest record, preserving every unrelated setting.
        const latest = await request<OctopAgent>(`/agents/${agent.agent_id}`);
        const config = { ...latest.config };
        if (values.device_id) {
          config.device_binding = {
            ...(values.device_id === LOCAL_TARGET
              ? { target_kind: "local", device_id: null }
              : {
                  target_kind: "device",
                  device_id: values.device_id,
                  ...(values.device_root_id
                    ? { root_id: values.device_root_id }
                    : {}),
                }),
            ...(values.device_working_dir?.trim()
              ? { working_dir: values.device_working_dir.trim() }
              : {}),
          };
        } else {
          delete config.device_binding;
        }
        body.config = config;
      }
      if (Object.keys(body).length === 0) {
        onClose();
        return;
      }
      const updated = await request<OctopAgent>(`/agents/${agent.agent_id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      message.success(t("common.saveSuccess"));
      onSaved({ ...agent, ...updated, agent_id: agent.agent_id });
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err, t("experts.patchFailed"), t));
    } finally {
      setSaving(false);
    }
  };

  const openFullSettings = () => {
    if (form.isFieldsTouched()) {
      modal.confirm({
        title: t("chat.agentProfile.discardDefaults"),
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        onOk: onFullSettings,
      });
    } else onFullSettings();
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message={t("chat.agentProfile.defaultsHint")}
      />
      {loading ? (
        <Spin />
      ) : (
        <>
          {error ? (
            <Alert
              type="error"
              showIcon
              message={error}
              action={
                !detail ? (
                  <Button onClick={() => setAttempt((value) => value + 1)}>
                    {t("common.retry")}
                  </Button>
                ) : undefined
              }
            />
          ) : null}
          {!canEdit ? (
            <Alert
              type="info"
              message={t("chat.agentProfile.defaultsReadOnly")}
            />
          ) : null}
          {detail ? (
            <Form form={form} layout="vertical" disabled={saving || !canEdit}>
              <ExpertModelDeviceFields
                form={form}
                models={models}
                modelsLoading={modelsLoading}
                devices={devices}
              />
            </Form>
          ) : null}
        </>
      )}
      {canEdit && detail ? (
        <Button type="link" disabled={saving} onClick={openFullSettings}>
          {t("chat.agentProfile.fullSettings")}
        </Button>
      ) : null}
      <Space style={{ display: "flex", justifyContent: "flex-end" }}>
        <Button onClick={onClose} disabled={saving}>
          {t("common.cancel")}
        </Button>
        {canEdit ? (
          <Button
            type="primary"
            onClick={() => void save()}
            loading={saving}
            disabled={loading || !detail || modelsLoading}
          >
            {t("common.save")}
          </Button>
        ) : null}
      </Space>
    </Space>
  );
}
