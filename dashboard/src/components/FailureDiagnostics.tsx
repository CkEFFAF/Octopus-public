import { Typography } from "antd";
import { useTranslation } from "react-i18next";

/** Receives only the server's allowlisted, content-free diagnostic object. */
export default function FailureDiagnostics({
  value,
}: {
  value?: Record<string, unknown> | null;
}) {
  const { t } = useTranslation();
  if (!value || !Object.keys(value).length) return null;
  const text = JSON.stringify(value, null, 2);
  return (
    <details style={{ marginTop: 10 }}>
      <summary>{t("common.failureDetails")}</summary>
      <Typography.Paragraph
        copyable={{ text }}
        style={{
          whiteSpace: "pre-wrap",
          overflowWrap: "anywhere",
          fontFamily: "monospace",
          fontSize: 12,
        }}
      >
        {text}
      </Typography.Paragraph>
    </details>
  );
}
