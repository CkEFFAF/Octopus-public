import type { ActivityNode } from "../../../api/modules/activity";
import type { ProgressTranslate } from "../../../utils/toolProgress";
import { previewText } from "./sessionPreview";

export function activityLabel(
  node: ActivityNode,
  t: ProgressTranslate,
): string {
  if (node.type === "job") {
    const name = String(node.details?.program || "").trim();
    return name
      ? t("workspace0034.jobProgram", { name: previewText(name, 64) })
      : t("workspace0034.nodeType.job");
  }
  const key = `tools.${node.name}`;
  const translated = t(key);
  if (translated !== key) return translated;
  if (/^[\da-f-]{24,}$/i.test(node.name))
    return t(`workspace0034.nodeType.${node.type}`);
  return previewText(node.name, 80);
}
