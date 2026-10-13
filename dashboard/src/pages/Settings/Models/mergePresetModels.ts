import type { FetchedProviderModel } from "./providerApi";
import type { ProviderModel, ProviderPresetModel } from "./useProviders";

/** Merge public catalog metadata without replacing saved user choices. */
export function mergePresetModels(
  current: ProviderModel[],
  fetched: FetchedProviderModel[],
  presets: ProviderPresetModel[] = [],
): ProviderModel[] {
  const catalog = new Map(presets.map((model) => [model.id, model]));
  const result = current.map((model) => {
    const preset = catalog.get(model.id);
    if (!preset) return model;
    return {
      ...model,
      use_responses_api: model.use_responses_api ?? preset.use_responses_api,
      name: model.name === model.id ? preset.name : model.name,
      input: model.input ?? preset.input,
      reasoning: model.reasoning ?? preset.reasoning ?? undefined,
      context_window:
        model.context_window ??
        preset.context_window ??
        preset.max_input_tokens ??
        undefined,
      max_tokens: model.max_tokens ?? preset.max_tokens ?? undefined,
      max_output_tokens:
        model.max_output_tokens ?? preset.max_output_tokens ?? undefined,
    };
  });
  const existing = new Set(result.map((model) => model.id));
  for (const model of fetched) {
    if (existing.has(model.id)) continue;
    const preset = catalog.get(model.id);
    result.push({
      id: model.id,
      use_responses_api: preset?.use_responses_api,
      name: preset?.name || model.name || model.id,
      enabled: false,
      input: preset?.input ?? ["text"],
      thinking: null,
      reasoning: preset?.reasoning ?? undefined,
      context_window:
        preset?.context_window ?? preset?.max_input_tokens ?? undefined,
      max_tokens: preset?.max_tokens ?? undefined,
      max_output_tokens: preset?.max_output_tokens ?? undefined,
    });
    existing.add(model.id);
  }
  return result;
}
