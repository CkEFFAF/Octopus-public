import { Button, Modal, Typography } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import styles from "./FailureDiagnostics.module.less";

/** Receives only the server's allowlisted, content-free diagnostic object. */
export default function FailureDiagnostics({
  value,
  summary,
}: {
  value?: Record<string, unknown> | null;
  summary?: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  if (!value || !Object.keys(value).length) return null;
  const text = JSON.stringify(value, null, 2);
  return (
    <>
      <Button type="link" size="small" onClick={() => setOpen(true)}>
        {t("common.failureDetails")}
      </Button>
      <Modal
        open={open}
        title={t("common.failureDetailsTitle")}
        width="min(640px, calc(100vw - 32px))"
        onCancel={() => setOpen(false)}
        footer={
          <Button onClick={() => setOpen(false)}>{t("common.close")}</Button>
        }
        destroyOnClose
      >
        {summary && <Typography.Paragraph>{summary}</Typography.Paragraph>}
        <Typography.Paragraph type="secondary">
          {t("common.failureDetailsHint")}
        </Typography.Paragraph>
        {Array.isArray(value.samples) &&
          typeof value.failed_count === "number" && (
            <Typography.Paragraph type="secondary">
              {t("common.failureSamplesHint", {
                count: value.failed_count,
                shown: value.samples.length,
              })}
            </Typography.Paragraph>
          )}
        {typeof value.input_tokens_estimate === "number" &&
          typeof value.input_limit_tokens === "number" && (
            <Typography.Paragraph>
              {t("common.failureBudget", {
                input: value.input_tokens_estimate,
                limit: value.input_limit_tokens,
              })}
            </Typography.Paragraph>
          )}
        <Typography.Paragraph copyable={{ text }}>
          {t("common.copyErrorForOctop")}
        </Typography.Paragraph>
        <Typography.Paragraph className={styles.diagnostic}>
          {text}
        </Typography.Paragraph>
      </Modal>
    </>
  );
}
