import type { ActivityNode } from "../../../api/modules/activity";
import type { ProgressTranslate } from "../../../utils/toolProgress";
import { previewText } from "./sessionPreview";

export function activityLabel(
  node: Pick<ActivityNode, "type" | "name" | "details">,
  t: ProgressTranslate,
): string {
  if (node.type === "job") {
    const title = String(node.details?.title || "").trim();
    if (title) return previewText(title, 120);
    const kind = node.details?.job_kind;
    if (["log", "log_gpu", "gpu"].includes(String(kind)))
      return t(`workspace0034.jobLabels.${kind}`, {
        name: String(node.details?.subject || ""),
      });
    const name = String(node.details?.program || "").trim();
    return name &&
      !/^[\da-f-]{24,}$/i.test(name) &&
      !/^(bash|sh|zsh|cmd|powershell)(\.exe)?$/i.test(name)
      ? t("workspace0034.jobProgram", { name: previewText(name, 64) })
      : t("workspace0034.nodeType.job");
  }
  if (node.type === "hook")
    return previewText(String(node.details?.title || node.name), 120);
  const key = `tools.${node.name}`;
  const translated = t(key);
  if (translated !== key) return translated;
  if (/^[\da-f-]{24,}$/i.test(node.name))
    return t(`workspace0034.nodeType.${node.type}`);
  return previewText(node.name, 80);
}
