import { describe, expect, it } from "vitest";
import { mergePresetModels } from "./mergePresetModels";

const preset = {
  id: "deepseek-flash",
  name: "DeepSeek V4.1 Flash",
  input: ["text", "image"],
  context_window: 1_000_000,
  max_output_tokens: 384_000,
  reasoning: true,
};

describe("model catalog synchronization", () => {
  it("preserves the request protocol of Responses-only presets", () => {
    const grok = { id: "grok-4.7", name: "Grok 4.7", use_responses_api: true };
    const [model] = mergePresetModels([], [grok], [grok]);
    expect(model.use_responses_api).toBe(true);
    expect(model.enabled).toBe(false);
  });
  it("uses official metadata for newly discovered models and leaves them disabled", () => {
    const [model] = mergePresetModels(
      [],
      [{ id: preset.id, name: preset.id }],
      [preset],
    );
    expect(model).toMatchObject({ ...preset, enabled: false, thinking: null });
    expect(model.max_tokens).toBeUndefined();
  });

  it("keeps custom names, enablement, limits and thinking choices", () => {
    const current = {
      id: preset.id,
      name: "我的模型",
      enabled: true,
      thinking: false,
      context_window: 1000,
      max_tokens: 200,
      max_output_tokens: 300,
      input: ["text"],
      reasoning: false,
    };
    expect(mergePresetModels([current], [preset], [preset])).toEqual([current]);
    expect(current.name).toBe("我的模型");
  });

  it("enriches a previously fetched bare ID without dropping older or custom models", () => {
    const old = { id: "custom-id", name: "Custom", enabled: true };
    const result = mergePresetModels(
      [old, { id: preset.id, name: preset.id, enabled: false }],
      [preset, preset, { id: "new-id", name: "New" }],
      [preset],
    );
    expect(result).toHaveLength(3);
    expect(result[0]).toEqual(old);
    expect(result[1]).toMatchObject({
      name: preset.name,
      input: preset.input,
      enabled: false,
    });
    expect(result[2]).toMatchObject({
      id: "new-id",
      name: "New",
      enabled: false,
    });
    expect(result[2].context_window).toBeUndefined();
  });
});
