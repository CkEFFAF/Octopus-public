import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Collapse,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
} from "antd";
import type {
  Binding,
  ContextPolicy,
  GraphDefinition,
  GraphNode,
} from "../../api/modules/workflowGraphs";
import { workflowGraphsApi } from "../../api/modules/workflowGraphs";

import { providerApi } from "../../api/modules/provider";
import {
  buildModelSelectOptions,
  type ModelPickerOption,
} from "../../utils/modelOptions";
import {
  ArgumentsEditor,
  BindingEditor,
  JsonField,
  MappingEditor,
  bindingPaths,
} from "./ValueEditors";
export { JsonField } from "./ValueEditors";

export function Inspector({
  graph,
  node,
  onChange,
  agents,
  tr,
}: {
  graph: GraphDefinition;
  node?: GraphNode;
  onChange: (graph: GraphDefinition) => void;
  agents: { agent_id: string; name: string }[];
  tr: (key: string) => string;
}) {
  const [models, setModels] = useState<ModelPickerOption[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelError, setModelError] = useState(false);
  const effectiveAgent = String(node?.agent_id || graph.agent_id || "");
  const agentNode = node?.kind === "agent";
  useEffect(() => {
    if (!agentNode) return;
    let stopped = false;
    setModels([]);
    setModelError(false);
    setModelsLoading(true);
    void providerApi
      .listResolvedModels(effectiveAgent || undefined)
      .then((items) => {
        if (!stopped) setModels(items);
      })
      .catch(() => {
        if (!stopped) setModelError(true);
      })
      .finally(() => {
        if (!stopped) setModelsLoading(false);
      });
    return () => {
      stopped = true;
    };
  }, [effectiveAgent, agentNode]);
  const paths = bindingPaths(graph);
  const modelOptions = buildModelSelectOptions(models, tr("modelAuto"));
  const selectedModel = String(node?.model || "");
  if (
    selectedModel &&
    !modelOptions.some((item) => item.value === selectedModel)
  )
    modelOptions.push({
      value: selectedModel,
      label: `${selectedModel} (${tr("modelUnavailable")})`,
    });
  const current = useRef({ graph, node, onChange });
  current.current = { graph, node, onChange };
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const patch = (changes: Partial<GraphNode>) =>
    node &&
    onChange({
      ...graph,
      nodes: graph.nodes.map((n) =>
        n.id === node.id ? { ...n, ...changes } : n,
      ),
    });
  const json = (key: string, fallback: unknown = {}) =>
    node && (
      <JsonField
        label={tr(key)}
        value={node[key] ?? fallback}
        onChange={(value) => patch({ [key]: value })}
      />
    );
  const field = (key: string, multiline = false) =>
    node && (
      <Form.Item label={tr(key)}>
        {multiline ? (
          <Input.TextArea
            aria-label={tr(key)}
            rows={5}
            value={String(node[key] ?? "")}
            onChange={(e) => patch({ [key]: e.target.value })}
          />
        ) : (
          <Input
            aria-label={tr(key)}
            value={String(node[key] ?? "")}
            onChange={(e) => patch({ [key]: e.target.value })}
          />
        )}
      </Form.Item>
    );
  const context: ContextPolicy = node?.context ?? { before: {}, after: {} };
  const before = context.before ?? {},
    after = context.after ?? {};
  const patchContext = (side: "before" | "after", changes: object) =>
    patch({
      context: { ...context, [side]: { ...context[side], ...changes } },
    });
  if (!node)
    return (
      <div className="wg-inspector">
        <h3>{tr("settings")}</h3>
        <Form layout="vertical" size="small">
          <Form.Item label={tr("name")}>
            <Input
              aria-label={tr("name")}
              value={graph.name}
              onChange={(e) => onChange({ ...graph, name: e.target.value })}
            />
          </Form.Item>
          <Form.Item label={tr("description")}>
            <Input.TextArea
              rows={3}
              aria-label={tr("description")}
              value={graph.description}
              onChange={(e) =>
                onChange({ ...graph, description: e.target.value })
              }
            />
          </Form.Item>
          <Form.Item label={tr("agent_id")}>
            <Select
              aria-label={tr("agent_id")}
              value={graph.agent_id || undefined}
              options={agents.map((a) => ({
                value: a.agent_id,
                label: a.name || a.agent_id,
              }))}
              onChange={(agent_id) => onChange({ ...graph, agent_id })}
            />
          </Form.Item>
          <Form.Item label={tr("origin_thread_id")} extra={tr("originHelp")}>
            <Input
              aria-label={tr("origin_thread_id")}
              value={graph.origin_thread_id}
              onChange={(e) =>
                onChange({ ...graph, origin_thread_id: e.target.value })
              }
            />
          </Form.Item>
          <Form.Item
            label={tr("execution_context_id")}
            extra={tr("sourceHelp")}
          >
            <Input
              aria-label={tr("execution_context_id")}
              value={graph.execution_context_id}
              onChange={(e) =>
                onChange({ ...graph, execution_context_id: e.target.value })
              }
            />
          </Form.Item>
          <MappingEditor
            label={tr("initial_variables")}
            value={Object.fromEntries(
              Object.entries(graph.initial_variables ?? {}).map(
                ([key, value]) => [key, { value }],
              ),
            )}
            paths={paths}
            tr={tr}
            literalOnly
            onChange={(value) =>
              onChange({
                ...graph,
                initial_variables: Object.fromEntries(
                  Object.entries(value).map(([key, binding]) => [
                    key,
                    "value" in binding ? binding.value : null,
                  ]),
                ),
              })
            }
          />
          <Collapse
            ghost
            items={[
              {
                key: "limits",
                label: tr("limits"),
                children: (
                  <>
                    {(
                      ["max_steps", "max_seconds", "max_parallel"] as const
                    ).map((key) => (
                      <Form.Item key={key} label={tr(key)}>
                        <InputNumber
                          value={
                            graph.limits?.[key] ??
                            {
                              max_steps: 100,
                              max_seconds: 86400,
                              max_parallel: 4,
                            }[key]
                          }
                          min={key === "max_seconds" ? 60 : 1}
                          max={
                            {
                              max_steps: 1000,
                              max_seconds: 2592000,
                              max_parallel: 4,
                            }[key]
                          }
                          onChange={(value) =>
                            onChange({
                              ...graph,
                              limits: {
                                max_steps: 100,
                                max_seconds: 86400,
                                max_parallel: 4,
                                ...graph.limits,
                                [key]: value,
                              },
                            })
                          }
                        />
                      </Form.Item>
                    ))}
                  </>
                ),
              },
              {
                key: "schedule",
                label: tr("schedule"),
                children: (
                  <>
                    <Form.Item label={tr("enabled")}>
                      <Switch
                        checked={!!graph.schedule?.enabled}
                        onChange={(enabled) =>
                          onChange({
                            ...graph,
                            schedule: {
                              cron: "0 9 * * *",
                              timezone: "",
                              overlap: "skip",
                              ...graph.schedule,
                              enabled,
                            },
                          })
                        }
                      />
                    </Form.Item>
                    {graph.schedule && (
                      <>
                        <Form.Item label={tr("cron")}>
                          <Input
                            value={graph.schedule.cron}
                            onChange={(e) =>
                              onChange({
                                ...graph,
                                schedule: {
                                  ...graph.schedule!,
                                  cron: e.target.value,
                                },
                              })
                            }
                          />
                        </Form.Item>
                        <Form.Item
                          label={tr("timezone")}
                          extra={tr("timezoneHelp")}
                        >
                          <Input
                            value={graph.schedule.timezone}
                            placeholder="Asia/Shanghai"
                            onChange={(e) =>
                              onChange({
                                ...graph,
                                schedule: {
                                  ...graph.schedule!,
                                  timezone: e.target.value,
                                },
                              })
                            }
                          />
                        </Form.Item>
                        <Form.Item label={tr("overlap")}>
                          <Select
                            value={graph.schedule.overlap}
                            options={["skip", "parallel"].map((v) => ({
                              value: v,
                              label: tr(v),
                            }))}
                            onChange={(overlap) =>
                              onChange({
                                ...graph,
                                schedule: { ...graph.schedule!, overlap },
                              })
                            }
                          />
                        </Form.Item>
                      </>
                    )}
                  </>
                ),
              },
              {
                key: "event",
                label: tr("event_start"),
                children: (
                  <Form.Item label={tr("enabled")} extra={tr("eventStartHelp")}>
                    <Switch
                      checked={!!graph.event_start}
                      onChange={(event_start) =>
                        onChange({ ...graph, event_start })
                      }
                    />
                  </Form.Item>
                ),
              },
            ]}
          />
        </Form>
      </div>
    );
  return (
    <div className="wg-inspector">
      <div className="wg-inspector-identity">
        <h3>{tr(`kind.${node.kind}`)}</h3>
        <small>{node.id}</small>
      </div>
      <p className="wg-field-hint">{tr(`nodeHint.${node.kind}`)}</p>
      <Form layout="vertical" size="small">
        {field("label")}
        {node.kind === "agent" && (
          <>
            {field("prompt", true)}
            <Form.Item label={tr("agent_id")}>
              <Select
                allowClear
                aria-label={tr("agent_id")}
                placeholder={tr("incomingExpert")}
                value={String(node.agent_id || "") || undefined}
                options={agents.map((a) => ({
                  value: a.agent_id,
                  label: a.name || a.agent_id,
                }))}
                onChange={(value) => patch({ agent_id: value || "" })}
              />
            </Form.Item>
            <Form.Item label={tr("model")} extra={tr("modelHelp")}>
              <Select
                aria-label={tr("model")}
                showSearch
                optionFilterProp="label"
                value={selectedModel}
                loading={modelsLoading}
                options={modelOptions}
                onChange={(model) => patch({ model })}
              />
            </Form.Item>
            {modelError && (
              <Alert type="warning" showIcon message={tr("modelLoadError")} />
            )}
            <Collapse
              ghost
              items={[
                {
                  key: "before",
                  label: tr("before"),
                  children: (
                    <>
                      <Form.Item label={tr("session")}>
                        <Select
                          aria-label={`${tr("before")} ${tr("session")}`}
                          value={before.session ?? "current"}
                          options={["current", "new"].map((v) => ({
                            value: v,
                            label: tr(v),
                          }))}
                          onChange={(session) =>
                            patchContext("before", { session })
                          }
                        />
                      </Form.Item>
                      <Form.Item label={tr("history")}>
                        <Select
                          aria-label={tr("history")}
                          value={before.history ?? "inherit"}
                          options={["inherit", "recent", "empty"].map((v) => ({
                            value: v,
                            label: tr(v),
                          }))}
                          onChange={(history) =>
                            patchContext("before", { history })
                          }
                        />
                      </Form.Item>
                      {before.history === "recent" && (
                        <Form.Item label={tr("recent_turns")}>
                          <InputNumber
                            min={1}
                            max={100}
                            aria-label={tr("recent_turns")}
                            value={before.recent_turns ?? 8}
                            onChange={(recent_turns) =>
                              patchContext("before", { recent_turns })
                            }
                          />
                        </Form.Item>
                      )}
                      <Form.Item label={tr("inject")} extra={tr("injectHelp")}>
                        <Input.TextArea
                          rows={3}
                          aria-label={tr("inject")}
                          value={before.inject ?? ""}
                          disabled={!!before.inject_from}
                          onChange={(e) =>
                            patchContext("before", { inject: e.target.value })
                          }
                        />
                      </Form.Item>
                      <Form.Item label={tr("inject_from")}>
                        <Input
                          placeholder="$.outputs.analyze.result"
                          value={
                            before.inject_from && "path" in before.inject_from
                              ? before.inject_from.path
                              : ""
                          }
                          onChange={(e) =>
                            patchContext("before", {
                              inject: null,
                              inject_from: e.target.value
                                ? { path: e.target.value }
                                : null,
                            })
                          }
                        />
                      </Form.Item>
                    </>
                  ),
                },
                {
                  key: "after",
                  label: tr("after"),
                  children: (
                    <>
                      {(["session", "context"] as const).map((key) => (
                        <Form.Item key={key} label={tr(key)}>
                          <Select
                            aria-label={`${tr("after")} ${tr(key)}`}
                            value={after[key] ?? "restore"}
                            options={["restore", "keep"].map((v) => ({
                              value: v,
                              label: tr(`after_${key}_${v}`),
                            }))}
                            onChange={(value) =>
                              patchContext("after", { [key]: value })
                            }
                          />
                        </Form.Item>
                      ))}
                      <Alert type="info" showIcon message={tr("contextHelp")} />
                    </>
                  ),
                },
              ]}
            />
          </>
        )}
        {node.kind === "script" && (
          <>
            <ArgumentsEditor
              value={(node.argv as string[]) ?? []}
              onChange={(argv) => patch({ argv })}
              tr={tr}
            />
            {field("cwd")}
            {field("execution_context_id")}
            <MappingEditor
              label={tr("env")}
              value={Object.fromEntries(
                Object.entries((node.env as Record<string, string>) ?? {}).map(
                  ([key, value]) => [key, { value }],
                ),
              )}
              paths={[]}
              tr={tr}
              literalOnly
              textOnly
              limit={64}
              onChange={(value) =>
                patch({
                  env: Object.fromEntries(
                    Object.entries(value).map(([key, binding]) => [
                      key,
                      "value" in binding ? String(binding.value) : "",
                    ]),
                  ),
                })
              }
            />
            {field("callback_node")}
          </>
        )}
        {["agent", "script"].includes(node.kind) && (
          <Form.Item label={tr("output_mode")}>
            <Select
              aria-label={tr("output_mode")}
              value={String(node.output_mode || "text")}
              options={[
                { value: "text", label: tr("text") },
                { value: "json", label: "JSON" },
              ]}
              onChange={(output_mode) => patch({ output_mode })}
            />
          </Form.Item>
        )}
        {node.kind === "condition" && (
          <>
            <Form.Item label={tr("left")}>
              <BindingEditor
                label={tr("left")}
                value={(node.left as Binding) ?? { value: true }}
                onChange={(left) => patch({ left })}
                paths={paths}
                tr={tr}
              />
            </Form.Item>
            <Form.Item label={tr("operator")}>
              <Select
                aria-label={tr("operator")}
                value={String(node.operator || "truthy")}
                options={[
                  "truthy",
                  "eq",
                  "ne",
                  "gt",
                  "gte",
                  "lt",
                  "lte",
                  "contains",
                ].map((value) => ({ value, label: tr(`operators.${value}`) }))}
                onChange={(operator) => patch({ operator })}
              />
            </Form.Item>
            {(node.operator || "truthy") !== "truthy" && (
              <Form.Item label={tr("right")}>
                <BindingEditor
                  label={tr("right")}
                  value={(node.right as Binding) ?? { value: true }}
                  onChange={(right) => patch({ right })}
                  paths={paths}
                  tr={tr}
                />
              </Form.Item>
            )}
          </>
        )}
        {node.kind === "event" && (
          <>
            {field("event_type")}
            {field("purpose", true)}
            <Form.Item label={tr("expires_in")}>
              <InputNumber
                min={60}
                max={2592000}
                value={Number(node.expires_in || 604800)}
                onChange={(expires_in) => patch({ expires_in })}
              />
            </Form.Item>
          </>
        )}
        {node.kind === "wait_event" && field("event_node")}
        {node.kind === "wait_time" && (
          <Form.Item label={tr("seconds")}>
            <InputNumber
              min={1}
              max={2592000}
              aria-label={tr("seconds")}
              value={Number(node.seconds || 60)}
              onChange={(seconds) => patch({ seconds })}
            />
          </Form.Item>
        )}
        {node.kind === "fork" && field("join_id")}
        {node.kind === "join" && (
          <>
            {field("fork_id")}
            {field("context_branch")}
            {json("merge")}
          </>
        )}
        <Collapse
          ghost
          defaultActiveKey={
            Object.keys(node.inputs ?? {}).length ||
            Object.keys(node.assign ?? {}).length
              ? ["bindings"]
              : []
          }
          items={[
            {
              key: "bindings",
              label: tr("bindings"),
              children: (
                <>
                  <p className="wg-field-hint">{tr("bindingHelp")}</p>
                  <MappingEditor
                    label={tr("inputs")}
                    value={node.inputs ?? {}}
                    onChange={(inputs) => patch({ inputs })}
                    paths={paths}
                    tr={tr}
                  />
                  <MappingEditor
                    label={tr("assign")}
                    value={node.assign ?? {}}
                    onChange={(assign) => patch({ assign })}
                    paths={paths}
                    tr={tr}
                  />
                </>
              ),
            },
            {
              key: "advanced",
              label: tr("advanced"),
              children: (
                <JsonField
                  label={tr("nodeDefinition")}
                  value={node}
                  normalize={async (value) => {
                    const replacement = value as GraphNode;
                    if (
                      !replacement ||
                      replacement.id !== node.id ||
                      !replacement.position ||
                      typeof replacement.label !== "string"
                    )
                      throw new Error(tr("invalidNode"));
                    const normalized = await workflowGraphsApi.normalize({
                      ...graph,
                      nodes: graph.nodes.map((n) =>
                        n.id === node.id ? replacement : n,
                      ),
                    });
                    return normalized.definition;
                  }}
                  onChange={(value) => {
                    if (
                      mounted.current &&
                      current.current.graph === graph &&
                      current.current.node?.id === node.id
                    ) {
                      current.current.onChange(value as GraphDefinition);
                    }
                  }}
                />
              ),
            },
          ]}
        />
      </Form>
    </div>
  );
}
