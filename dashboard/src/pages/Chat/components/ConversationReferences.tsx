import { useState } from "react";
import { Button, Popover } from "antd";
import { Link2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ConversationSourceRef } from "../../../api/modules/conversationMetadata";
import styles from "./ConversationOverview.module.less";

/** Source bodies stay unloaded until a specific reference is selected. */
export default function ConversationReferences({
  refs,
  onRead,
}: {
  refs: ConversationSourceRef[];
  onRead: (ref: ConversationSourceRef) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [limit, setLimit] = useState(10);
  const unique = [
    ...new Map(
      refs.map((ref) => [`${ref.kind}:${ref.id}:${ref.revision ?? ""}`, ref]),
    ).values(),
  ];
  if (!unique.length) return null;
  if (unique.length === 1)
    return (
      <Button
        type="link"
        size="small"
        className={styles.sourceChip}
        icon={<Link2 size={12} />}
        onClick={() => onRead(unique[0])}
      >
        {t("conversationMetadata.source")}
      </Button>
    );
  return (
    <Popover
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      title={t("conversationMetadata.sourcesCount", { count: unique.length })}
      content={
        open && (
          <div className={styles.referenceList}>
            {unique.slice(0, limit).map((ref, index) => (
              <Button
                key={`${ref.kind}:${ref.id}:${ref.revision ?? ""}`}
                type="text"
                size="small"
                onClick={() => {
                  setOpen(false);
                  onRead(ref);
                }}
              >
                {t("conversationMetadata.source")} {index + 1}
              </Button>
            ))}
            {unique.length > limit && (
              <Button
                type="link"
                size="small"
                onClick={() => setLimit((value) => value + 10)}
              >
                {t("conversationMetadata.moreSources")}
              </Button>
            )}
          </div>
        )
      }
    >
      <Button
        type="link"
        size="small"
        className={styles.sourceChip}
        icon={<Link2 size={12} />}
      >
        {t("conversationMetadata.sourcesCount", { count: unique.length })}
      </Button>
    </Popover>
  );
}
