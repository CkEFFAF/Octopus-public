import FailureDiagnostics from "../../../components/FailureDiagnostics";
import { useCallback, useEffect, useRef, useState } from "react";
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
  type OrganizationAge,
  type OrganizationStatus,
} from "../../../api/modules/conversationMetadata";
import { octopThreadsApi } from "../../../api/modules/octopThreads";
import { apiErrorMessage } from "../../../utils/apiError";
import styles from "./index.module.less";
import OrganizationHistory from "./OrganizationHistory";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../../utils/formatMessageTime";

export default function ConversationMetadataSettings() {
  const { t } = useTranslation();
  const translate = useRef(t);
  translate.current = t;
  const timezone = useServerTimezone();
  const [ageFilter, setAgeFilter] = useState<OrganizationAge>("all");
  const [statusFilter, setStatusFilter] = useState<OrganizationStatus>("all");
  const { message } = App.useApp();
  const navigate = useNavigate();
  const { agents } = useAgent();
  const [form] = Form.useForm<MetadataSettings>();
  const [settings, setSettings] = useState<MetadataSettingsView | null>(null);
  const confirmedSettings = useRef<MetadataSettingsView | null>(null);
  const nextSettings = useRef<MetadataSettings | null>(null);
  const applying = useRef(false);
  const [applyError, setApplyError] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [batchOpen, setBatchOpen] = useState(false);
  const [failedBatch, setFailedBatch] = useState<string | null>(null);
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
  const batchEpoch = useRef(0);
  const pending = Boolean(batch && (batch.queued || batch.running));
  const recovered = batch?.recovered ?? 0;
  const unresolved = Math.max(0, (batch?.failed ?? 0) - recovered);
  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      const epoch = batchEpoch.current;
      try {
        const value = await conversationMetadataApi.historyBatch();
        if (alive && epoch === batchEpoch.current) {
          setBatch(value);
          setBatchError("");
        }
      } catch (err) {
        if (alive)
          setBatchError(
            apiErrorMessage(
              err,
              translate.current("conversationMetadata.generationFailed"),
            ),
          );
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);
  const load = useCallback(async () => {
    try {
      setError("");
      const value = await conversationMetadataApi.settings();
      confirmedSettings.current = value;
      setSettings(value);
      form.setFieldsValue(value);
    } catch (err) {
      setError(
        apiErrorMessage(
          err,
          translate.current("conversationMetadata.generationFailed"),
        ),
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
    if (!confirmedSettings.current) return;
    nextSettings.current = values;
    if (applying.current) return;
    applying.current = true;
    setSaving(true);
    setApplyError("");
    try {
      while (nextSettings.current) {
        const desired = nextSettings.current;
        nextSettings.current = null;
        const value = await conversationMetadataApi.saveSettings({
          revision: confirmedSettings.current.revision,
          title_enabled: desired.title_enabled,
          brief_enabled: desired.brief_enabled,
          title_model: desired.title_model,
          brief_model: desired.brief_model,
        });
        confirmedSettings.current = value;
        setSettings(value);
        if (!nextSettings.current) form.setFieldsValue(value);
      }
    } catch (err) {
      nextSettings.current = null;
      // A failed automatic write must not leave controls pretending to be applied.
      form.setFieldsValue(confirmedSettings.current);
      setApplyError(
        apiErrorMessage(err, t("conversationMetadata.generationFailed"), t),
      );
    } finally {
      applying.current = false;
      setSaving(false);
    }
  };
  const enqueue = async () => {
    if (applying.current) return;
    setBatchBusy(true);
    try {
      const value = await conversationMetadataApi.startHistoryBatch({
        command_id: commandId,
        ...(ageFilter !== "all" ? { age_filter: ageFilter } : {}),
        ...(statusFilter !== "all" ? { status_filter: statusFilter } : {}),
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
            onValuesChange={(_changed, values) => void save(values)}
          >
            <div className={styles.applyStatus} aria-live="polite">
              {saving
                ? t("conversationMetadata.applying")
                : applyError
                ? t("conversationMetadata.applyFailed")
                : t("conversationMetadata.applied")}
            </div>
            {applyError && (
              <Alert
                type="error"
                showIcon
                className={styles.notice}
                message={t("conversationMetadata.applyFailed")}
                description={applyError}
                action={
                  <Button
                    onClick={() => {
                      setApplyError("");
                      void load();
                    }}
                  >
                    {t("common.refresh")}
                  </Button>
                }
              />
            )}
            {(!settings.title_available || !settings.brief_available) && (
              <Alert
                type="info"
                showIcon
                className={styles.notice}
                message={t("conversationMetadata.modelUnavailableHint")}
              />
            )}
            <div className={styles.modelGrid}>
              <section className={styles.modelCard}>
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
              </section>
              <section className={styles.modelCard}>
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
                      {
                        value: "same",
                        label: t("conversationMetadata.sameTitle"),
                      },
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
              </section>
            </div>
            <Alert
              className={styles.notice}
              type="info"
              message={t("conversationMetadata.manualPriority")}
              description={t("conversationMetadata.historyPolicy")}
            />
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
            disabled={!settings || pending || saving}
            onClick={() => {
              setBatchScope("all");
              setBatchOpen(true);
            }}
          >
            {t(
              pending
                ? "conversationMetadata.batchInProgress"
                : ageFilter !== "all" || statusFilter !== "all"
                ? "organizationHistory.organizeFiltered"
                : "conversationMetadata.organizeAll",
            )}
          </Button>
          {pending && batch && (
            <Button
              danger
              loading={batchBusy}
              onClick={async () => {
                batchEpoch.current += 1;
                setBatchBusy(true);
                try {
                  setBatch(
                    await conversationMetadataApi.cancelHistoryBatch(
                      batch.batch_id,
                    ),
                  );
                } catch (e) {
                  setBatchError(apiErrorMessage(e, t("common.error"), t));
                } finally {
                  setBatchBusy(false);
                }
              }}
            >
              {t("conversationMetadata.stopOrganizing")}
            </Button>
          )}
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
                    : unresolved || batch.cancelled
                    ? "exception"
                    : "success"
                }
              />
              <Typography.Paragraph>
                {t("organizationHistory.batchResult")} ·{" "}
                {t("conversationMetadata.batchProgress", { ...batch })}
              </Typography.Paragraph>
              <p className={styles.historyHint}>
                {t("organizationHistory.batchSnapshotHint")}
              </p>
              {recovered > 0 && (
                <Alert
                  type="success"
                  showIcon
                  message={t("organizationHistory.recoveredCount", {
                    count: recovered,
                  })}
                />
              )}
              {Boolean(batch.started_at) && (
                <p className={styles.historyHint}>
                  {t("organizationHistory.batchStarted")}{" "}
                  {formatServerDateTime(batch.started_at!, timezone)}
                  {Boolean(batch.finished_at) && (
                    <>
                      {" "}
                      · {t("organizationHistory.batchFinished")}{" "}
                      {formatServerDateTime(batch.finished_at!, timezone)}
                    </>
                  )}
                </p>
              )}
              {Boolean(unresolved || batch.cancelled) && (
                <Typography.Text type="warning">
                  {t("conversationMetadata.batchFailureHint")}
                </Typography.Text>
              )}
              {unresolved > 0 &&
                Object.entries(batch.errors ?? {}).map(([code, count]) => {
                  const reason = t(
                    `conversationMetadata.errors.${code}`,
                    t("conversationMetadata.generationFailed"),
                  );
                  return (
                    <Alert
                      key={code}
                      type="warning"
                      showIcon
                      className={styles.failureRow}
                      message={`${reason} · ${t(
                        "conversationMetadata.failureCount",
                        { count },
                      )}`}
                      action={
                        <FailureDiagnostics
                          summary={reason}
                          value={{
                            code,
                            failed_count: count,
                            samples: batch.failures?.filter(
                              (item) => item.code === code,
                            ),
                          }}
                        />
                      }
                    />
                  );
                })}
              {Boolean(batch.failed) && (
                <Button
                  size="small"
                  onClick={() => {
                    setFailedBatch(batch.batch_id);
                  }}
                >
                  {t("organizationHistory.viewBatchFailures")}
                </Button>
              )}
            </div>
          )}
          <OrganizationHistory
            age={ageFilter}
            status={statusFilter}
            pending={pending}
            onFilter={(age, status) => {
              setAgeFilter(age);
              setStatusFilter(status);
            }}
          />
        </section>
      </div>
      <Modal
        open={Boolean(failedBatch)}
        title={t("organizationHistory.viewBatchFailures")}
        footer={null}
        width={800}
        destroyOnClose
        onCancel={() => setFailedBatch(null)}
      >
        {failedBatch && (
          <OrganizationHistory
            batchId={failedBatch}
            age="all"
            status="failed"
            pending={pending}
            onFilter={() => undefined}
          />
        )}
      </Modal>
      <Modal
        open={batchOpen}
        title={t("conversationMetadata.organizeHistory")}
        onCancel={() => setBatchOpen(false)}
        onOk={() => void enqueue()}
        okText={t("conversationMetadata.startOrganizing")}
        okButtonProps={{
          disabled:
            pending ||
            saving ||
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
          <Radio value="all">
            {t(
              ageFilter !== "all" || statusFilter !== "all"
                ? "organizationHistory.filteredScope"
                : "conversationMetadata.allHistory",
            )}
          </Radio>
          <Radio value="selected">
            {t("conversationMetadata.selectedHistory")}
          </Radio>
        </Radio.Group>
        <p>
          {t(
            batchScope === "all"
              ? ageFilter !== "all" || statusFilter !== "all"
                ? "organizationHistory.filteredHint"
                : "conversationMetadata.historyAllHint"
              : "conversationMetadata.historySelectionHint",
          )}
        </p>
        {(ageFilter !== "all" || statusFilter !== "all") && (
          <Alert
            type="info"
            showIcon
            message={`${t("organizationHistory.appliedFilters")} ${t(
              `organizationHistory.ages.${ageFilter}`,
            )} · ${t(`organizationHistory.status.${statusFilter}`)}`}
          />
        )}
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
