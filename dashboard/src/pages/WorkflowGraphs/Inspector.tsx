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
  ContextPolicy,
  GraphDefinition,
  GraphNode,
} from "../../api/modules/workflowGraphs";
import { workflowGraphsApi } from "../../api/modules/workflowGraphs";

export function JsonField({
  label,
  value,
  onChange,
  normalize,
}: {
  label: string;
  value: unknown;
  onChange: (value: unknown) => void;
  normalize?: (value: unknown) => Promise<unknown>;
}) {
  const serialized = JSON.stringify(value ?? {}, null, 2);
  const [text, setText] = useState(serialized),
    [error, setError] = useState("");
  const request = useRef(0);
  useEffect(() => {
    request.current += 1;
    setText(serialized);
    setError("");
    return () => {
      request.current += 1;
    };
  }, [serialized]);
  return (
    <Form.Item label={label} validateStatus={error ? "error" : ""} help={error}>
      <Input.TextArea
        aria-label={label}
        value={text}
        rows={4}
        spellCheck={false}
        className="wg-json"
        onChange={(event) => {
          request.current += 1;
          setText(event.target.value);
          setError("");
        }}
        onBlur={async () => {
          const sequence = ++request.current;
          try {
            const parsed: unknown = JSON.parse(text);
            const result = normalize ? await normalize(parsed) : parsed;
            if (sequence !== request.current) return;
            onChange(result);
            setError("");
          } catch (e) {
            if (sequence === request.current) setError(String(e));
          }
        }}
      />
    </Form.Item>
  );
}

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
          <JsonField
            label={tr("initial_variables")}
            value={graph.initial_variables}
            onChange={(value) =>
              onChange({
                ...graph,
                initial_variables: value as Record<string, unknown>,
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
      <h3>{tr(`kind.${node.kind}`)}</h3>
      <small>{node.id}</small>
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
            {field("model")}
            <Collapse
              defaultActiveKey={["before", "after"]}
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
            {json("argv", [])}
            {field("cwd")}
            {field("execution_context_id")}
            {json("env")}
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
            {json("left", { value: true })}
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
                ].map((value) => ({ value, label: value }))}
                onChange={(operator) => patch({ operator })}
              />
            </Form.Item>
            {json("right", { value: true })}
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
          items={[
            {
              key: "bindings",
              label: tr("bindings"),
              children: (
                <>
                  <Alert type="info" message={tr("bindingHelp")} />
                  {json("inputs")}
                  {json("assign")}
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
