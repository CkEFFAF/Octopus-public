import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Binding } from "../../api/modules/workflowGraphs";
import { ArgumentsEditor, MappingEditor } from "./ValueEditors";

afterEach(cleanup);
const tr = (key: string) => key;

function Mappings() {
  const [value, setValue] = useState<Record<string, Binding>>({
    improved: { path: "$.outputs.evaluate.result.improved" },
  });
  return (
    <>
      <MappingEditor
        label="inputs"
        value={value}
        onChange={setValue}
        paths={[]}
        tr={tr}
      />
      <output data-testid="value">{JSON.stringify(value)}</output>
    </>
  );
}

describe("workflow value editors", () => {
  it("edits paths and typed literals without changing text into JSON values", () => {
    render(<Mappings />);
    fireEvent.change(
      screen.getByRole("combobox", { name: "inputs improved mappingValue" }),
      { target: { value: "$.vars.evidence" } },
    );
    expect(screen.getByTestId("value")).toHaveTextContent(
      '{"improved":{"path":"$.vars.evidence"}}',
    );
    fireEvent.mouseDown(
      screen.getByRole("combobox", {
        name: "inputs improved mappingValue valueType",
      }),
    );
    fireEvent.click(screen.getByText("valueTypes.text"));
    fireEvent.change(
      screen.getByRole("textbox", { name: "inputs improved mappingValue" }),
      { target: { value: "true" } },
    );
    expect(screen.getByTestId("value")).toHaveTextContent(
      '{"improved":{"value":"true"}}',
    );
  });

  it("retains a mapping when a rename collides with another key", () => {
    render(<Mappings />);
    fireEvent.click(screen.getByRole("button", { name: "addMapping inputs" }));
    const key = screen.getByRole("textbox", {
      name: "inputs value_1 mappingKey",
    });
    fireEvent.change(key, { target: { value: "improved" } });
    fireEvent.blur(key);
    expect(screen.getByRole("alert")).toHaveTextContent("uniqueKey");
    expect(JSON.parse(screen.getByTestId("value").textContent!)).toEqual({
      improved: { path: "$.outputs.evaluate.result.improved" },
      value_1: { value: "" },
    });
  });

  it("preserves one argv item containing spaces and quotes", () => {
    function Arguments() {
      const [value, setValue] = useState(["python", "experiment runner.py"]);
      return (
        <>
          <ArgumentsEditor value={value} onChange={setValue} tr={tr} />
          <output data-testid="value">{JSON.stringify(value)}</output>
        </>
      );
    }
    render(<Arguments />);
    fireEvent.change(screen.getByRole("textbox", { name: "argument 1" }), {
      target: { value: 'a "quoted" path.py' },
    });
    expect(JSON.parse(screen.getByTestId("value").textContent!)).toEqual([
      "python",
      'a "quoted" path.py',
    ]);
    fireEvent.click(screen.getByRole("button", { name: "addArgument" }));
    expect(screen.getByRole("textbox", { name: "argument 2" })).toHaveValue("");
  });
});
