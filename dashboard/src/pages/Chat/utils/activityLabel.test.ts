import { expect, it } from "vitest";
import type { ActivityNode } from "../../../api/modules/activity";
import { activityLabel } from "./activityLabel";

it("prefers the agent's business title and retains conservative legacy labels", () => {
  const t = (key: string, values?: Record<string, unknown>) =>
    `${key}${values?.name ? `:${values.name}` : ""}`;
  const node = (details: Record<string, unknown>) =>
    ({ type: "job", name: "bash", details }) as ActivityNode;
  expect(
    activityLabel(node({ title: "核对验证结果", program: "bash" }), t),
  ).toBe("核对验证结果");
  expect(
    activityLabel(node({ job_kind: "log_gpu", subject: "probes.log" }), t),
  ).toBe("workspace0034.jobLabels.log_gpu:probes.log");
  expect(activityLabel(node({ program: "bash" }), t)).toBe(
    "workspace0034.nodeType.job",
  );
  expect(
    activityLabel(node({ program: "c7ee1e6ff8da4ba7ff9b7e3817d42a8" }), t),
  ).toBe("workspace0034.nodeType.job");
});
