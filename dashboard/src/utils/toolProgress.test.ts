import { createInstance } from "i18next";
import { describe, expect, it } from "vitest";
import zh from "../locales/zh.json";
import { toolProgress } from "./toolProgress";
import { activityLabel } from "../pages/Chat/utils/activityLabel";

const i18n = createInstance();
await i18n.init({
  lng: "zh",
  resources: { zh: { translation: zh } },
  interpolation: { escapeValue: false },
});
const t = i18n.t.bind(i18n);
describe("observed tool feedback", () => {
  it("explains a concrete file operation without asking another model", () => {
    const view = toolProgress(
      "read_file",
      { file_path: "inbound/需求.txt" },
      JSON.stringify({ total_lines: 12, error: null }),
      t,
    );
    expect(view.action).toContain("读取");
    expect(view.action).toContain("需求.txt");
    expect(view.outcome).toBe("已返回结果");
    expect(view.facts).toContain("12 行");
  });
  it("does not report a failed operation as done", () => {
    const view = toolProgress(
      "execute",
      { command: "python train.py" },
      JSON.stringify({ result: { returncode: 2 } }),
      t,
    );
    expect(view.outcome).toBe("执行失败");
    expect(view.facts).toContain("退出码 2");
    expect(
      toolProgress("external", {}, "provider error", t, "error").failed,
    ).toBe(true);
  });
  it("distinguishes command acceptance from completion", () => {
    expect(
      toolProgress(
        "job_start",
        {},
        JSON.stringify({
          status: "running",
          job_id: "c7ee1e6ff8da4ba7ff9b7e3817d42a8",
        }),
        t,
      ).outcome,
    ).toBe("后台继续运行");
    const status = toolProgress(
      "job_status",
      { job_id: "c7ee1e6ff8da4ba7ff9b7e3817d42a8" },
      undefined,
      t,
    );
    expect(status.action).toBe("检查后台任务进度");
    expect(status.action).not.toContain("c7ee");
  });
  it("shows a job program and keeps identifiers out of the title", () => {
    const node = {
      id: "job:opaque",
      type: "job",
      name: "c7ee1e6ff8da4ba7ff9b7e3817d42a8",
      status: "running",
      updated_at: 1,
      dependencies_known: false,
    };
    expect(activityLabel(node, t)).not.toContain("c7ee");
    expect(activityLabel({ ...node, details: { program: "训练.py" } }, t)).toBe(
      "运行 训练.py",
    );
  });
});
