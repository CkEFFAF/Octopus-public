import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  App,
  Button,
  Form,
  Modal,
  Progress,
  Radio,
  Select,
  Space,
  Spin,
  Switch,
  Typography,
} from "antd";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import PageShell from "../../../layouts/PageShell";
import { useAgent } from "../../../context/AgentContext";
import {
  conversationMetadataApi,
  metadataCommandId,
  type HistoryBatch,
  type MetadataSettings,
  type MetadataSettingsView,
} from "../../../api/modules/conversationMetadata";
import { octopThreadsApi } from "../../../api/modules/octopThreads";
import { apiErrorMessage } from "../../../utils/apiError";
import styles from "./index.module.less";

export default function ConversationMetadataSettings() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const { agents } = useAgent();
  const [form] = Form.useForm<MetadataSettings>();
  const [settings, setSettings] = useState<MetadataSettingsView | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchScope, setBatchScope] = useState<"all" | "selected">("all");
  const [batch, setBatch] = useState<HistoryBatch | null>(null);
  const [batchError, setBatchError] = useState("");
  const [commandId, setCommandId] = useState(metadataCommandId);
  const [batchAgent, setBatchAgent] = useState("");
  const [threads, setThreads] = useState<{ value: string; label: string }[]>(
    [],
  );
  const [selected, setSelected] = useState<string[]>([]);
  const [batchBusy, setBatchBusy] = useState(false);
  const pending = Boolean(batch && (batch.queued || batch.running));
  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      try {
        const value = await conversationMetadataApi.historyBatch();
        if (alive) {
          setBatch(value);
          setBatchError("");
        }
      } catch (err) {
        if (alive)
          setBatchError(
            apiErrorMessage(err, t("conversationMetadata.generationFailed")),
          );
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [t]);
  const load = useCallback(async () => {
    try {
      setError("");
      const value = await conversationMetadataApi.settings();
      setSettings(value);
      form.setFieldsValue(value);
    } catch (err) {
      setError(
        apiErrorMessage(err, t("conversationMetadata.generationFailed")),
      );
    }
  }, [form]);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (!batchOpen || batchScope !== "selected" || !batchAgent) return;
    let alive = true;
    setThreads([]);
    setSelected([]);
    if (batchOpen && batchAgent) {
      setBatchBusy(true);
      void octopThreadsApi
        .list(batchAgent, 50)
        .then((rows) => {
          if (alive)
            setThreads(
              rows.map((row) => ({
                value: row.thread_id,
                label: row.title || t("conversationMetadata.untitled"),
              })),
            );
        })
        .catch((err) => {
          if (alive)
            message.error(
              apiErrorMessage(err, t("conversationMetadata.generationFailed")),
            );
        })
        .finally(() => {
          if (alive) setBatchBusy(false);
        });
    }
    return () => {
      alive = false;
    };
  }, [batchOpen, batchScope, batchAgent, message, t]);
  const save = async (values: MetadataSettings) => {
    if (!settings) return;
    setSaving(true);
    try {
      const value = await conversationMetadataApi.saveSettings({
        revision: settings.revision,
        title_enabled: values.title_enabled,
        brief_enabled: values.brief_enabled,
        title_model: values.title_model,
        brief_model: values.brief_model,
      });
      setSettings(value);
      form.setFieldsValue(value);
      message.success(t("conversationMetadata.saved"));
    } catch (err) {
      message.error(
        apiErrorMessage(err, t("conversationMetadata.generationFailed")),
      );
    } finally {
      setSaving(false);
    }
  };
  const enqueue = async () => {
    setBatchBusy(true);
    try {
      const value = await conversationMetadataApi.startHistoryBatch({
        command_id: commandId,
        ...(batchScope === "selected"
          ? { agent_id: batchAgent, thread_ids: selected }
          : {}),
      });
      setBatch(value);
      setBatchError("");
      setCommandId(metadataCommandId());
      message.success(
        t("conversationMetadata.batchQueued", { count: value.total }),
      );
      setBatchOpen(false);
    } catch (err) {
      message.error(
        apiErrorMessage(err, t("conversationMetadata.generationFailed")),
      );
    } finally {
      setBatchBusy(false);
    }
  };
  const modelOptions = [
    { value: "account", label: t("conversationMetadata.followAccount") },
    ...(settings?.models ?? []),
  ];
  return (
    <PageShell
      title={t("conversationMetadata.settingsTitle")}
      subtitle={t("conversationMetadata.settingsSubtitle")}
      actions={
        <Button onClick={() => navigate("/admin/models")}>
          {t("conversationMetadata.configureModels")}
        </Button>
      }
    >
      <div className={styles.content}>
        {error && (
          <Alert
            type="error"
            showIcon
            message={error}
            action={
              <Button onClick={() => void load()}>{t("common.retry")}</Button>
            }
          />
        )}
        {!settings && !error && <Spin />}
        {settings && (
          <Form
            form={form}
            layout="vertical"
            onFinish={(values) => void save(values)}
          >
            {(!settings.title_available || !settings.brief_available) && (
              <Alert
                type="info"
                showIcon
                className={styles.notice}
                message={t("conversationMetadata.modelUnavailableHint")}
              />
            )}
            <Form.Item
              name="title_enabled"
              valuePropName="checked"
              label={t("conversationMetadata.autoTitle")}
            >
              <Switch aria-label={t("conversationMetadata.autoTitle")} />
            </Form.Item>
            <Form.Item
              name="title_model"
              label={t("conversationMetadata.titleModel")}
              rules={[{ required: true }]}
              extra={t("conversationMetadata.titlePolicy")}
            >
              <Select
                options={modelOptions}
                showSearch
                optionFilterProp="label"
                aria-label={t("conversationMetadata.titleModel")}
              />
            </Form.Item>
            <Typography.Paragraph type="secondary">
              {t("conversationMetadata.effectiveModel", {
                model:
                  settings.resolved_title_model ||
                  t("conversationMetadata.unconfigured"),
              })}
            </Typography.Paragraph>
            <div className={styles.divider} />
            <Form.Item
              name="brief_enabled"
              valuePropName="checked"
              label={t("conversationMetadata.autoBrief")}
            >
              <Switch aria-label={t("conversationMetadata.autoBrief")} />
            </Form.Item>
            <Form.Item
              name="brief_model"
              label={t("conversationMetadata.briefModel")}
              rules={[{ required: true }]}
              extra={t("conversationMetadata.briefPolicy")}
            >
              <Select
                options={[
                  { value: "same", label: t("conversationMetadata.sameTitle") },
                  ...modelOptions,
                ]}
                showSearch
                optionFilterProp="label"
                aria-label={t("conversationMetadata.briefModel")}
              />
            </Form.Item>
            <Typography.Paragraph type="secondary">
              {t("conversationMetadata.effectiveModel", {
                model:
                  settings.resolved_brief_model ||
                  t("conversationMetadata.unconfigured"),
              })}
            </Typography.Paragraph>
            <Alert
              className={styles.notice}
              type="info"
              message={t("conversationMetadata.manualPriority")}
              description={t("conversationMetadata.historyPolicy")}
            />
            <Space wrap>
              <Button type="primary" htmlType="submit" loading={saving}>
                {t("common.save")}
              </Button>
              <Button
                onClick={() => {
                  form.setFieldsValue(settings);
                }}
              >
                {t("common.cancel")}
              </Button>
            </Space>
          </Form>
        )}
        <section
          className={styles.history}
          aria-label={t("conversationMetadata.organizeHistory")}
        >
          <Typography.Title level={4}>
            {t("conversationMetadata.organizeHistory")}
          </Typography.Title>
          <Typography.Paragraph>
            {t("conversationMetadata.historyAllHint")}
          </Typography.Paragraph>
          <Button
            type="primary"
            disabled={!settings || pending}
            onClick={() => {
              setBatchScope("all");
              setBatchOpen(true);
            }}
          >
            {t(
              pending
                ? "conversationMetadata.batchInProgress"
                : "conversationMetadata.organizeAll",
            )}
          </Button>
          {batchError && <Alert type="error" showIcon message={batchError} />}
          {batch && (
            <div className={styles.batchProgress} role="status">
              <Progress
                percent={
                  batch.total
                    ? Math.round(
                        (100 * (batch.ready + batch.failed + batch.cancelled)) /
                          batch.total,
                      )
                    : 100
                }
                status={
                  pending
                    ? "active"
                    : batch.failed || batch.cancelled
                    ? "exception"
                    : "success"
                }
              />
              <Typography.Paragraph>
                {t("conversationMetadata.batchProgress", { ...batch })}
              </Typography.Paragraph>
              {Boolean(batch.failed || batch.cancelled) && (
                <Typography.Text type="warning">
                  {t("conversationMetadata.batchFailureHint")}
                </Typography.Text>
              )}
            </div>
          )}
        </section>
      </div>
      <Modal
        open={batchOpen}
        title={t("conversationMetadata.organizeHistory")}
        onCancel={() => setBatchOpen(false)}
        onOk={() => void enqueue()}
        okText={t("conversationMetadata.startOrganizing")}
        okButtonProps={{
          disabled:
            pending ||
            (batchScope === "selected" && (!batchAgent || !selected.length)) ||
            !settings?.brief_available ||
            (settings.title_enabled && !settings.title_available),
        }}
        confirmLoading={batchBusy}
      >
        <Radio.Group
          value={batchScope}
          onChange={(event) => setBatchScope(event.target.value)}
          aria-label={t("conversationMetadata.historyScope")}
        >
          <Radio value="all">{t("conversationMetadata.allHistory")}</Radio>
          <Radio value="selected">
            {t("conversationMetadata.selectedHistory")}
          </Radio>
        </Radio.Group>
        <p>
          {t(
            batchScope === "all"
              ? "conversationMetadata.historyAllHint"
              : "conversationMetadata.historySelectionHint",
          )}
        </p>
        {(!settings?.brief_available ||
          (settings.title_enabled && !settings.title_available)) && (
          <Alert
            className={styles.notice}
            type="warning"
            showIcon
            message={t("conversationMetadata.modelUnavailableHint")}
          />
        )}
        {batchScope === "selected" && (
          <Space direction="vertical" className={styles.full}>
            <Select
              className={styles.full}
              aria-label={t("conversationMetadata.agent")}
              placeholder={t("conversationMetadata.agent")}
              value={batchAgent || undefined}
              onChange={setBatchAgent}
              options={agents.map((a) => ({
                value: a.agent_id,
                label: a.name,
              }))}
            />
            <Select
              className={styles.full}
              mode="multiple"
              aria-label={t("conversationMetadata.selectThreads")}
              placeholder={t("conversationMetadata.selectThreads")}
              value={selected}
              onChange={setSelected}
              options={threads}
              loading={batchBusy}
              maxCount={50}
            />
          </Space>
        )}
      </Modal>
    </PageShell>
  );
}
