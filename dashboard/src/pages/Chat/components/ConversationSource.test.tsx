import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import ConversationSource from "./ConversationSource";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, vars?: { name: string }) =>
      vars ? `${key}: ${vars.name}` : key,
  }),
}));
afterEach(cleanup);

it("shows ACP source with a safe return link to the parent conversation", () => {
  render(
    <MemoryRouter>
      <ConversationSource
        agentId="expert"
        origin={{
          category: "agent_collaboration",
          actor: { kind: "agent", id: "expert", name: "GPU专家" },
          collaboration_source: {
            kind: "acp",
            runner_name: "GrokBot",
            device_id: "gpu",
            parent_thread_id: "parent/1",
          },
        }}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText("GrokBot")).toBeInTheDocument();
  expect(screen.getByText("GPU专家")).toBeInTheDocument();
  expect(
    screen.getByText("collaboration.sourceDevice: gpu"),
  ).toBeInTheDocument();
  expect(screen.getByRole("link")).toHaveAttribute(
    "href",
    "/chat/expert/parent%2F1",
  );
});

it("does not label an ordinary legacy conversation as collaboration", () => {
  const { container } = render(
    <MemoryRouter>
      <ConversationSource agentId="expert" origin={{}} />
    </MemoryRouter>,
  );
  expect(container).toBeEmptyDOMElement();
});
