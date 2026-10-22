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
    expect(model.source).toBe("remote");
  });
  it("uses official metadata for newly discovered models and leaves them disabled", () => {
    const [model] = mergePresetModels(
      [],
      [{ id: preset.id, name: preset.id }],
      [preset],
    );
    expect(model).toMatchObject({
      ...preset,
      enabled: false,
      thinking: null,
      source: "remote",
    });
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
    const [merged] = mergePresetModels([current], [preset], [preset]);
    expect(merged).toMatchObject({ ...current, source: "remote" });
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
    expect(result[0]).toMatchObject({ ...old, source: "user" });
    expect(result[1]).toMatchObject({
      name: preset.name,
      input: preset.input,
      enabled: false,
      source: "remote",
    });
    expect(result[2]).toMatchObject({
      id: "new-id",
      name: "New",
      enabled: false,
      source: "remote",
    });
    expect(result[2].context_window).toBeUndefined();
  });

  it("never deletes user-only models and tags source=user", () => {
    const custom = {
      id: "my-custom-model",
      name: "Mine",
      enabled: true,
    };
    const result = mergePresetModels([custom], [{ id: "gpt-x", name: "gpt-x" }], [
      preset,
    ]);
    expect(result.find((m) => m.id === "my-custom-model")).toMatchObject({
      id: "my-custom-model",
      enabled: true,
      source: "user",
    });
    expect(result.find((m) => m.id === "gpt-x")?.source).toBe("remote");
    expect(result.find((m) => m.id === preset.id)?.source).toBe("preset");
  });

  it("adds preset-only models when remote catalog omits them", () => {
    const result = mergePresetModels([], [], [preset]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      id: preset.id,
      name: preset.name,
      enabled: false,
      source: "preset",
    });
  });
});
