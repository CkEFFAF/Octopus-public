import { useEffect, useRef, useState } from "react";
import { AutoComplete, Button, Form, Input, InputNumber, Select } from "antd";
import { Plus, X } from "lucide-react";
import type {
  Binding,
  GraphDefinition,
} from "../../api/modules/workflowGraphs";

type Translate = (key: string) => string;

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

export function bindingPaths(graph: GraphDefinition): string[] {
  return [
    ...Object.keys(graph.initial_variables ?? {}).map((key) => `$.vars.${key}`),
    ...graph.nodes.flatMap((node) => [
      ...Object.keys(node.assign ?? {}).map((key) => `$.vars.${key}`),
      `$.outputs.${node.id}`,
      `$.outputs.${node.id}.result`,
    ]),
    "$.event",
  ].filter((path, index, all) => all.indexOf(path) === index);
}

export function BindingEditor({
  label,
  value,
  onChange,
  paths,
  tr,
  literalOnly = false,
  textOnly = false,
}: {
  label: string;
  value: Binding;
  onChange: (value: Binding) => void;
  paths: string[];
  tr: Translate;
  literalOnly?: boolean;
  textOnly?: boolean;
}) {
  const literal = "value" in value ? value.value : undefined;
  const type =
    "path" in value
      ? "path"
      : literal === null
      ? "null"
      : typeof literal === "object"
      ? "json"
      : typeof literal === "number"
      ? "number"
      : typeof literal === "boolean"
      ? "boolean"
      : "text";
  return (
    <div className="wg-binding-value">
      {!textOnly && (
        <Select
          aria-label={`${label} ${tr("valueType")}`}
          value={type}
          options={(literalOnly
            ? ["text", "number", "boolean", "json", "null"]
            : ["path", "text", "number", "boolean", "json", "null"]
          ).map((key) => ({ value: key, label: tr(`valueTypes.${key}`) }))}
          onChange={(next) =>
            onChange(
              next === "path"
                ? { path: "$.vars." }
                : {
                    value: (
                      {
                        text: "",
                        number: 0,
                        boolean: true,
                        json: {},
                        null: null,
                      } as Record<string, unknown>
                    )[next],
                  },
            )
          }
        />
      )}
      {type === "path" ? (
        <AutoComplete
          aria-label={label}
          value={"path" in value ? value.path : ""}
          options={paths.map((path) => ({ value: path }))}
          filterOption={(input, option) => !!option?.value.includes(input)}
          placeholder="$.outputs.analyze.result"
          onChange={(path) => onChange({ path })}
        />
      ) : type === "boolean" ? (
        <Select
          aria-label={label}
          value={String(literal)}
          options={[
            { value: "true", label: tr("booleanTrue") },
            { value: "false", label: tr("booleanFalse") },
          ]}
          onChange={(next) => onChange({ value: next === "true" })}
        />
      ) : type === "number" ? (
        <InputNumber
          aria-label={label}
          value={literal as number}
          onChange={(next) => next !== null && onChange({ value: next })}
        />
      ) : type === "json" ? (
        <JsonField
          label={label}
          value={literal}
          onChange={(next) => onChange({ value: next })}
        />
      ) : type === "null" ? (
        <span className="wg-field-hint">{tr("nullValue")}</span>
      ) : (
        <Input
          aria-label={label}
          value={String(literal ?? "")}
          onChange={(e) => onChange({ value: e.target.value })}
        />
      )}
    </div>
  );
}

function MappingRow({
  name,
  binding,
  label,
  names,
  onRename,
  onChange,
  onRemove,
  paths,
  tr,
  literalOnly,
  textOnly,
}: {
  name: string;
  binding: Binding;
  label: string;
  names: string[];
  onRename: (next: string) => void;
  onChange: (binding: Binding) => void;
  onRemove: () => void;
  paths: string[];
  tr: Translate;
  literalOnly?: boolean;
  textOnly?: boolean;
}) {
  const [key, setKey] = useState(name);
  const invalid = !key.trim() || (key !== name && names.includes(key));
  return (
    <div className="wg-mapping-row">
      <div className="wg-mapping-key">
        <Input
          aria-label={`${label} ${name} ${tr("mappingKey")}`}
          value={key}
          status={invalid ? "error" : undefined}
          onChange={(e) => setKey(e.target.value)}
          onBlur={() => {
            if (!invalid && key !== name) onRename(key);
          }}
        />
        <Button
          type="text"
          aria-label={`${tr("removeMapping")} ${name}`}
          icon={<X size={14} />}
          onClick={onRemove}
        />
      </div>
      {invalid && (
        <small role="alert" className="wg-field-error">
          {tr("uniqueKey")}
        </small>
      )}
      <BindingEditor
        label={`${label} ${name} ${tr("mappingValue")}`}
        value={binding}
        onChange={onChange}
        paths={paths}
        tr={tr}
        literalOnly={literalOnly}
        textOnly={textOnly}
      />
    </div>
  );
}

export function MappingEditor({
  label,
  value,
  onChange,
  paths,
  tr,
  literalOnly = false,
  textOnly = false,
  limit = 32,
}: {
  label: string;
  value: Record<string, Binding>;
  onChange: (value: Record<string, Binding>) => void;
  paths: string[];
  tr: Translate;
  literalOnly?: boolean;
  textOnly?: boolean;
  limit?: number;
}) {
  return (
    <div className="wg-mapping-editor" role="group" aria-label={label}>
      <div className="wg-field-heading">
        <strong>{label}</strong>
        <Button
          type="text"
          size="small"
          disabled={Object.keys(value).length >= limit}
          icon={<Plus size={14} />}
          aria-label={`${tr("addMapping")} ${label}`}
          onClick={() => {
            let index = 1;
            while (`value_${index}` in value) index += 1;
            onChange({ ...value, [`value_${index}`]: { value: "" } });
          }}
        >
          {tr("addMapping")}
        </Button>
      </div>
      {!Object.keys(value).length && (
        <p className="wg-field-hint">{tr("noMappings")}</p>
      )}
      {Object.entries(value).map(([name, binding]) => (
        <MappingRow
          key={name}
          name={name}
          binding={binding}
          label={label}
          names={Object.keys(value)}
          paths={paths}
          tr={tr}
          literalOnly={literalOnly}
          textOnly={textOnly}
          onRename={(next) =>
            onChange(
              Object.fromEntries(
                Object.entries(value).map(([key, item]) => [
                  key === name ? next : key,
                  item,
                ]),
              ),
            )
          }
          onChange={(next) => onChange({ ...value, [name]: next })}
          onRemove={() =>
            onChange(
              Object.fromEntries(
                Object.entries(value).filter(([key]) => key !== name),
              ),
            )
          }
        />
      ))}
    </div>
  );
}

export function ArgumentsEditor({
  value,
  onChange,
  tr,
}: {
  value: string[];
  onChange: (value: string[]) => void;
  tr: Translate;
}) {
  return (
    <div className="wg-arguments" role="group" aria-label={tr("argv")}>
      <div className="wg-field-heading">
        <strong>{tr("argv")}</strong>
        <Button
          type="text"
          size="small"
          disabled={value.length >= 64}
          icon={<Plus size={14} />}
          onClick={() => onChange([...value, ""])}
        >
          {tr("addArgument")}
        </Button>
      </div>
      <p className="wg-field-hint">{tr("argvHelp")}</p>
      {value.map((argument, index) => (
        <div className="wg-argument" key={index}>
          <span>{index}</span>
          <Input
            aria-label={`${tr("argument")} ${index}`}
            value={argument}
            placeholder={index === 0 ? tr("executable") : tr("argument")}
            onChange={(e) =>
              onChange(
                value.map((item, i) => (i === index ? e.target.value : item)),
              )
            }
          />
          <Button
            type="text"
            aria-label={`${tr("removeArgument")} ${index}`}
            icon={<X size={14} />}
            onClick={() => onChange(value.filter((_, i) => i !== index))}
          />
        </div>
      ))}
    </div>
  );
}
