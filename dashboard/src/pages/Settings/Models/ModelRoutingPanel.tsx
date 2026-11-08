import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Input,
  InputNumber,
  Select,
  Space,
  Spin,
  Switch,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  MODEL_TASKS,
  modelRoutingApi,
  type ModelRoutingConfig,
  type ModelRoutingView,
  type ModelRouteDecision,
  type ModelTask,
} from "../../../api/modules/modelRouting";
import { useUnsavedChangesWarning } from "../../../hooks/useUnsavedChangesWarning";
import styles from "./ModelRoutingPanel.module.less";

export default function ModelRoutingPanel() {
  const { t } = useTranslation();
  const [view, setView] = useState<ModelRoutingView | null>(null);
  const [draft, setDraft] = useState<ModelRoutingConfig>({
    enabled: false,
    tasks: {},
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [text, setText] = useState("");
  const [task, setTask] = useState<ModelTask | undefined>();
  const [images, setImages] = useState(false);
  const [contextTokens, setContextTokens] = useState(0);
  const [preview, setPreview] = useState<ModelRouteDecision | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const dirty =
    Boolean(view) &&
    JSON.stringify(draft) !==
      JSON.stringify({ enabled: view?.enabled, tasks: view?.tasks });
  useUnsavedChangesWarning(dirty);
  const accept = useCallback((next: ModelRoutingView) => {
    setView(next);
    setDraft({ enabled: next.enabled, tasks: next.tasks });
    setPreview(null);
  }, []);
  useEffect(() => {
    let active = true;
    modelRoutingApi
      .get()
      .then((next) => {
        if (active) accept(next);
      })
      .catch((e) => {
        if (active) setError(String(e));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [accept]);
  const save = async () => {
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      accept(await modelRoutingApi.save(draft));
      setSaved(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };
  const tryPreview = async () => {
    setPreviewing(true);
    setError("");
    try {
      setPreview(
        await modelRoutingApi.preview({
          text,
          task,
          has_images: images,
          context_tokens: contextTokens,
        }),
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setPreviewing(false);
    }
  };
  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const next = await modelRoutingApi.get();
      setView(next);
      if (!dirty) accept(next);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };
  return (
    <Card
      title={t("modelRouting.title")}
      className={styles.panel}
      extra={
        <Switch
          aria-label={t("modelRouting.enable")}
          checked={draft.enabled}
          disabled={!view || saving}
          onChange={(enabled) => {
            setDraft({ ...draft, enabled });
            setSaved(false);
            setPreview(null);
          }}
        />
      }
    >
      <Typography.Paragraph type="secondary">
        {t("modelRouting.description")}
      </Typography.Paragraph>
      {error && <Alert type="error" showIcon message={error} />}
      {saved && (
        <Alert type="success" showIcon message={t("modelRouting.saved")} />
      )}
      {loading && !view ? (
        <Spin />
      ) : (
        view && (
          <>
            <div className={styles.tasks}>
              {MODEL_TASKS.map((kind) => {
                const selected = draft.tasks[kind] ?? "";
                const options = [
                  { value: "", label: t("modelRouting.auto") },
                  ...view.models
                    .filter(
                      (m) => kind !== "vision" || m.input.includes("image"),
                    )
                    .map((m) => ({
                      value: m.value,
                      label: `${m.name || m.model} · ${m.provider_name} · ${
                        m.model
                      }`,
                    })),
                ];
                if (selected && !options.some((o) => o.value === selected))
                  options.push({
                    value: selected,
                    label: t("modelRouting.unavailableSelection", {
                      model: selected,
                    }),
                  });
                const resolved = view.resolved[kind];
                return (
                  <div className={styles.task} key={kind}>
                    <label htmlFor={`model-route-${kind}`}>
                      {t(`modelRouting.tasks.${kind}`)}
                    </label>
                    <Select
                      id={`model-route-${kind}`}
                      aria-label={t(`modelRouting.tasks.${kind}`)}
                      value={selected}
                      showSearch
                      optionFilterProp="label"
                      options={options}
                      disabled={saving}
                      onChange={(value) => {
                        setDraft({
                          ...draft,
                          tasks: { ...draft.tasks, [kind]: value || null },
                        });
                        setSaved(false);
                        setPreview(null);
                      }}
                    />
                    <Typography.Text type="secondary">
                      {t("modelRouting.effective", {
                        model: resolved.model || t("modelRouting.noModel"),
                      })}
                      {view.auxiliary_overrides[kind]
                        ? ` · ${t("modelRouting.dedicatedOverride")}`
                        : ""}
                    </Typography.Text>
                  </div>
                );
              })}
            </div>
            <Typography.Paragraph type="secondary">
              {t("modelRouting.auxiliaryNote")}{" "}
              <a href="/settings/conversation-metadata">
                {t("modelRouting.auxiliaryLink")}
              </a>
            </Typography.Paragraph>
            <Space wrap>
              <Button
                type="primary"
                onClick={() => void save()}
                loading={saving}
                disabled={!dirty}
              >
                {t("common.save")}
              </Button>
              <Button
                onClick={() => void refresh()}
                loading={loading}
                disabled={saving}
              >
                {t("modelRouting.refresh")}
              </Button>
            </Space>
            <div className={styles.preview}>
              <Typography.Title level={5}>
                {t("modelRouting.previewTitle")}
              </Typography.Title>
              <Typography.Paragraph type="secondary">
                {t("modelRouting.previewDescription")}
              </Typography.Paragraph>
              <Input.TextArea
                aria-label={t("modelRouting.previewInput")}
                placeholder={t("modelRouting.previewInput")}
                value={text}
                maxLength={20000}
                rows={2}
                onChange={(e) => {
                  setText(e.target.value);
                  setPreview(null);
                }}
              />
              <Space wrap>
                <Select
                  aria-label={t("modelRouting.previewTask")}
                  className={styles.taskSelect}
                  value={task ?? "auto"}
                  options={[
                    { value: "auto", label: t("modelRouting.detectTask") },
                    ...MODEL_TASKS.map((value) => ({
                      value,
                      label: t(`modelRouting.tasks.${value}`),
                    })),
                  ]}
                  onChange={(value) => {
                    setTask(
                      value === "auto" ? undefined : (value as ModelTask),
                    );
                    setPreview(null);
                  }}
                />
                <Checkbox
                  checked={images}
                  onChange={(e) => {
                    setImages(e.target.checked);
                    setPreview(null);
                  }}
                >
                  {t("modelRouting.hasImages")}
                </Checkbox>
                <InputNumber
                  aria-label={t("modelRouting.contextTokens")}
                  min={0}
                  max={10000000}
                  value={contextTokens}
                  onChange={(value) => {
                    setContextTokens(value ?? 0);
                    setPreview(null);
                  }}
                  placeholder={t("modelRouting.contextTokens")}
                />
                <Button
                  onClick={() => void tryPreview()}
                  loading={previewing}
                  disabled={dirty || saving}
                >
                  {t(dirty ? "modelRouting.saveFirst" : "modelRouting.preview")}
                </Button>
              </Space>
              {preview && (
                <Alert
                  type={preview.available ? "info" : "warning"}
                  showIcon
                  message={t("modelRouting.decision", {
                    task: t(`modelRouting.tasks.${preview.task}`),
                    model: preview.model || t("modelRouting.noModel"),
                  })}
                  description={t(`modelRouting.reasons.${preview.reason}`, {
                    defaultValue: t("modelRouting.reasons.account_default"),
                  })}
                />
              )}
            </div>
          </>
        )
      )}
      {!loading && !view && (
        <Button onClick={() => void refresh()}>{t("common.retry")}</Button>
      )}
    </Card>
  );
}
