/**
 * PresetProviderModal — create a cloud provider from a built-in preset (right-side drawer).
 * Local runtimes (Ollama / ONNX) use LocalServiceCard + ProviderConfigModal instead.
 */
import { useEffect, useMemo, useState } from "react";
import { Button, Divider, Drawer, Form, Input } from "antd";
import { message } from "@/utils/antdMessage";

import { Download, Zap } from "lucide-react";
import { useTranslation } from "react-i18next";
import { request } from "../../../../../api/request";
import { enrichWizardModel } from "../../wizardModelMeta";
import { mergePresetModels } from "../../mergePresetModels";
import type {
  ProviderModel,
  ProviderPreset,
  ProviderRow,
} from "../../useProviders";
import { isEmbeddingModel } from "../../useProviders";
import { CodexOAuthConnect } from "../CodexOAuthConnect";
import { fetchProviderModels, testProviderDraft } from "../../providerApi";
import { ModelListEditor } from "./ModelListEditor";
import styles from "../../index.module.less";

interface PresetProviderModalProps {
  preset: ProviderPreset;
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}

interface PresetForm {
  name: string;
  base_url: string;
  api_key?: string;
  kind: string;
}

export function PresetProviderModal({
  preset,
  open,
  onClose,
  onSaved,
}: PresetProviderModalProps) {
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [draftModels, setDraftModels] = useState<ProviderModel[]>([]);
  const [form] = Form.useForm<PresetForm>();
  const isCodexOAuth = preset.auth_method === "codex_oauth";
  const apiKey = Form.useWatch("api_key", form) as string | undefined;
  const canTest = !!apiKey?.trim();

  const draftProvider = useMemo<ProviderRow>(
    () => ({
      id: 0,
      name: (form.getFieldValue("name") as string | undefined) || preset.name,
      kind: preset.protocol,
      base_url:
        (form.getFieldValue("base_url") as string | undefined) ||
        preset.base_url,
      api_key: (form.getFieldValue("api_key") as string | undefined) || null,
      models: draftModels,
      note: null,
      enabled: true,
    }),
    [draftModels, form, preset.base_url, preset.name, preset.protocol],
  );

  useEffect(() => {
    if (open) {
      const baseModels: ProviderModel[] = preset.models.map((m) => {
        const meta = enrichWizardModel(m, t);
        const ctx =
          m.context_window ?? m.max_input_tokens ?? meta.context_window;
        const entry: ProviderModel = {
          id: m.id,
          use_responses_api: m.use_responses_api,
          max_output_tokens: m.max_output_tokens ?? undefined,
          name: m.name,
          enabled: true,
          input: meta.input,
          thinking: null,
        };
        if (meta.reasoning) entry.reasoning = true;
        if (ctx) entry.context_window = ctx;
        if (meta.max_tokens) entry.max_tokens = meta.max_tokens;
        return entry;
      });
      setDraftModels(baseModels);
      form.resetFields();
      form.setFieldsValue({
        name: preset.name,
        base_url: preset.base_url,
        kind: preset.protocol,
      });
    }
  }, [open, preset, form, t]);

  const handleFetchModels = async () => {
    if (isCodexOAuth) return;
    try {
      const values = await form.validateFields(["base_url", "api_key"]);
      const key = values.api_key?.trim();
      if (!key) {
        message.warning(t("models.pleaseEnterApiKey"));
        return;
      }
      setFetchingModels(true);
      const result = await fetchProviderModels({
        kind: "openai",
        api_key: key,
        base_url: values.base_url?.trim() || preset.base_url,
        name: preset.id,
      });
      if (!result.ok) {
        message.error(
          t("models.fetchModelsFailed", {
            error: result.error ?? "unknown",
          }),
        );
        return;
      }
      const fetched = result.models ?? [];
      if (fetched.length === 0) {
        message.info(t("models.fetchModelsNoNew"));
        return;
      }
      const merged = mergePresetModels(draftModels, fetched, preset.models);
      if (JSON.stringify(merged) === JSON.stringify(draftModels)) {
        message.info(t("models.fetchModelsNoNew"));
        return;
      }
      setDraftModels((models) =>
        mergePresetModels(models, fetched, preset.models),
      );
      message.success(
        t("models.fetchModelsMerged", {
          count: merged.length - draftModels.length,
        }),
      );
    } catch (err) {
      if (err && typeof err === "object" && "errorFields" in err) return;
      message.error(
        err instanceof Error
          ? err.message
          : t("models.fetchModelsFailed", { error: "unknown" }),
      );
    } finally {
      setFetchingModels(false);
    }
  };

  const testDraftModel = async (modelId: string) => {
    const values = await form.validateFields(["name", "base_url", "api_key"]);
    const key = values.api_key?.trim();
    if (!key) {
      return { ok: false, error: t("models.pleaseEnterApiKey") };
    }
    return testProviderDraft({
      name: values.name.trim(),
      kind: preset.protocol,
      api_key: key,
      base_url: values.base_url?.trim() || preset.base_url,
      model_id: modelId,
      use_responses_api: draftModels.find((m) => m.id === modelId)
        ?.use_responses_api,
      embedding: isEmbeddingModel(draftModels.find((m) => m.id === modelId)),
    });
  };

  const handleTest = async () => {
    if (isCodexOAuth) return;
    try {
      const values = await form.validateFields();
      const modelId =
        draftModels.find((m) => m.enabled !== false)?.id || draftModels[0]?.id;
      if (!modelId) {
        message.warning(t("models.testDraftNeedModel"));
        return;
      }
      const key = values.api_key?.trim();
      if (!key) {
        message.warning(t("models.pleaseEnterApiKey"));
        return;
      }
      setTesting(true);
      const result = await testDraftModel(modelId);
      if (result.ok) {
        message.success(
          t("models.testSuccess", {
            name: values.name,
            time: result.latency_ms ?? 0,
          }),
        );
      } else {
        message.error(
          t("models.testConnectionFailed", {
            error: result.error ?? "unknown",
          }),
        );
      }
    } catch (err) {
      if (err && typeof err === "object" && "errorFields" in err) return;
      message.error(
        err instanceof Error ? err.message : t("models.testFailedSimple"),
      );
    } finally {
      setTesting(false);
    }
  };

  const handleSubmit = async () => {
    if (isCodexOAuth) return;
    try {
      const values = await form.validateFields();
      setSaving(true);

      await request<ProviderRow>("/providers", {
        method: "POST",
        body: JSON.stringify({
          name: values.name.trim(),
          kind: preset.protocol,
          base_url: values.base_url?.trim() || null,
          api_key: values.api_key?.trim() || null,
          models: draftModels,
        }),
      });
      message.success(
        t("models.providerCreatedSimple", { name: values.name.trim() }),
      );
      await onSaved();
      onClose();
    } catch (err) {
      if (err && typeof err === "object" && "errorFields" in err) return;
      const msg =
        err instanceof Error ? err.message : t("models.createFailedSimple");
      if (typeof msg === "string" && msg.includes("UNIQUE")) {
        message.error(t("models.presetNameExists"));
      } else {
        message.error(msg);
      }
    } finally {
      setSaving(false);
    }
  };

  const apiKeyPlaceholder = preset.api_key_prefix
    ? `${preset.api_key_prefix}...`
    : "sk-...";

  return (
    <Drawer
      title={t("models.setupPreset", { name: preset.name })}
      open={open}
      onClose={onClose}
      destroyOnHidden
      width={640}
      placement="right"
      footer={
        isCodexOAuth ? (
          <Button onClick={onClose}>{t("common.cancel")}</Button>
        ) : (
          <div className={styles.modalFooter}>
            <div className={styles.modalFooterLeft} />
            <div className={styles.modalFooterRight}>
              <Button onClick={onClose}>{t("common.cancel")}</Button>
              <Button
                type="primary"
                loading={saving}
                onClick={() => void handleSubmit()}
              >
                {t("common.create")}
              </Button>
            </div>
          </div>
        )
      }
    >
      {isCodexOAuth ? (
        <CodexOAuthConnect
          onSuccess={async () => {
            await onSaved();
            onClose();
          }}
        />
      ) : (
        <>
          <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
            <Form.Item
              name="name"
              label={t("models.nameLabel")}
              rules={[{ required: true }]}
            >
              <Input placeholder={preset.name} />
            </Form.Item>

            <Form.Item name="kind" label={t("models.kindLabel")}>
              <Input disabled style={{ color: "var(--fn-text-secondary)" }} />
            </Form.Item>

            <Form.Item
              name="base_url"
              label="Base URL"
              extra={t("models.baseUrlExtra")}
            >
              <Input placeholder={preset.base_url || "https://..."} />
            </Form.Item>

            <Form.Item
              name="api_key"
              label="API Key"
              rules={[
                {
                  required: true,
                  message: t("models.pleaseEnterApiKey"),
                },
              ]}
            >
              <Input.Password
                placeholder={apiKeyPlaceholder}
                visibilityToggle
              />
            </Form.Item>
          </Form>

          <div style={{ marginBottom: 16 }}>
            <Button
              icon={<Zap size={14} />}
              loading={testing}
              onClick={() => void handleTest()}
            >
              {t("models.testConnection")}
            </Button>
            <Button
              icon={<Download size={14} />}
              loading={fetchingModels}
              onClick={() => void handleFetchModels()}
              style={{ marginLeft: 8 }}
            >
              {t("models.fetchModels")}
            </Button>
          </div>

          <Divider orientation="left" style={{ fontSize: 13 }}>
            {t("models.manageModels")}
          </Divider>
          <ModelListEditor
            provider={draftProvider}
            models={draftModels}
            onModelsChange={setDraftModels}
            apiPrefix="/providers"
            canTest={canTest}
            onTestModel={(modelId) => testDraftModel(modelId)}
          />
        </>
      )}
    </Drawer>
  );
}
