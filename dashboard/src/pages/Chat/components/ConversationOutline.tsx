import { useState, type ReactNode } from "react";
import { Alert, Segmented, Space, Tree, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type {
  BriefItem,
  ConversationBrief,
  ConversationSourceRef,
} from "../../../api/modules/conversationMetadata";

export type OutlineGroup = { key: string; label: string; items: BriefItem[] };
const singleLine = (text: string) => text.replace(/[\r\n\t]+/g, " ").trim();

export function exportOutline(
  title: string,
  groups: OutlineGroup[],
  format: "markdown" | "mermaid" | "todo",
) {
  if (format === "mermaid") {
    const quote = (text: string) =>
      singleLine(text)
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    return [
      "mindmap",
      `  root["${quote(title)}"]`,
      ...groups.flatMap((group, i) => [
        `    g${i}["${quote(group.label)}"]`,
        ...group.items.map(
          (item, j) => `      n${i}_${j}["${quote(item.text)}"]`,
        ),
      ]),
    ].join("\n");
  }
  const included =
    format === "todo"
      ? groups.filter((group) =>
          ["remaining", "nextActions", "blockers"].includes(group.key),
        )
      : groups;
  return [
    "# " + singleLine(title),
    ...included.flatMap((group) => [
      "",
      "## " + group.label,
      ...group.items.map(
        (item) =>
          (format === "todo" ? "- [ ] " : "- ") +
          singleLine(item.text) +
          (item.source_refs.length
            ? " (" +
              item.source_refs
                .map((ref) => ref.kind + ":" + ref.id)
                .join(", ") +
              ")"
            : ""),
      ),
    ]),
  ].join("\n");
}

/** A projection of the current, source-backed brief; no additional model calls. */
export default function ConversationOutline({
  brief,
  references,
}: {
  brief: ConversationBrief;
  references: (refs: ConversationSourceRef[]) => ReactNode;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState("standard");
  const [format, setFormat] = useState<"markdown" | "mermaid" | "todo">(
    "markdown",
  );
  const groups: OutlineGroup[] = [
    {
      key: "objective",
      label: t("conversationMetadata.objective"),
      items: brief.overview.objective
        ? [{ text: brief.overview.objective, source_refs: [] }]
        : [],
    },
    {
      key: "decisions",
      label: t("conversationMetadata.decisions"),
      items: brief.decisions,
    },
    {
      key: "completed",
      label: t("conversationMetadata.completed"),
      items: brief.progress.completed,
    },
    {
      key: "inProgress",
      label: t("conversationMetadata.inProgress"),
      items: brief.progress.in_progress,
    },
    {
      key: "blockers",
      label: t("conversationMetadata.blockers"),
      items: brief.progress.blockers,
    },
    {
      key: "remaining",
      label: t("conversationMetadata.remaining"),
      items: brief.progress.remaining,
    },
    {
      key: "nextActions",
      label: t("conversationMetadata.nextActions"),
      items: brief.progress.next_actions,
    },
    {
      key: "findings",
      label: t("conversationMetadata.findings"),
      items: brief.findings,
    },
    {
      key: "artifacts",
      label: t("conversationMetadata.artifacts"),
      items: brief.artifact_refs.map((a) => ({
        text: a.path,
        source_refs: [],
      })),
    },
  ].filter(
    (group) =>
      group.items.length &&
      (mode !== "compact" ||
        ["decisions", "completed", "nextActions"].includes(group.key)),
  );
  const title =
    brief.title ||
    brief.overview.one_liner ||
    t("conversationMetadata.overviewTitle");
  return (
    <Space direction="vertical" style={{ width: "100%", minWidth: 0 }}>
      <Alert
        type="info"
        showIcon
        message={t("conversationMetadata.outlineHint")}
      />
      <Segmented
        aria-label={t("conversationMetadata.outlineMode")}
        value={mode}
        onChange={setMode}
        options={[
          {
            value: "standard",
            label: t("conversationMetadata.outlineStandard"),
          },
          { value: "compact", label: t("conversationMetadata.outlineCompact") },
        ]}
      />
      <Tree
        showLine
        defaultExpandAll
        key={mode}
        style={{ overflowWrap: "anywhere", minWidth: 0 }}
        treeData={groups.map((group) => ({
          key: group.key,
          title: group.label,
          children: group.items.map((item, i) => ({
            key: group.key + i,
            title: (
              <span style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>
                {item.text}
                {references(item.source_refs)}
              </span>
            ),
          })),
        }))}
      />
      <Segmented
        value={format}
        onChange={(value) => setFormat(value as typeof format)}
        options={["markdown", "mermaid", "todo"]}
      />
      <Typography.Paragraph
        copyable={{ text: exportOutline(title, groups, format) }}
        style={{ marginTop: 12 }}
      >
        {t("conversationMetadata.copyOutline")}
      </Typography.Paragraph>
      <pre
        style={{
          maxHeight: 240,
          maxWidth: "100%",
          overflow: "auto",
          whiteSpace: "pre-wrap",
          overflowWrap: "anywhere",
          padding: 12,
          background: "var(--fn-bg-secondary)",
          borderRadius: 8,
        }}
      >
        {exportOutline(title, groups, format)}
      </pre>
    </Space>
  );
}
