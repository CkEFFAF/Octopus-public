import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import zh from "../../../locales/zh.json";
import ChatWorkStatus from "./ChatWorkStatus";

vi.unmock("react-i18next");
const i18n = createInstance();
await i18n.init({
  lng: "zh",
  resources: { zh: { translation: zh } },
  interpolation: { escapeValue: false },
});
it("shows concise activity and leaves progress and model details accessible", async () => {
  const onShowProgress = vi.fn();
  const onContinueChat = vi.fn();
  render(
    <I18nextProvider i18n={i18n}>
      <ChatWorkStatus
        phase="running_tool"
        startedAt={Date.now() - 105000}
        currentTool={{
          name: "execute",
          arguments: JSON.stringify({
            command:
              "cd /project && python - <<'PY'\nprint('opaque script')\nPY",
          }),
        }}
        modelRoute={{
          task: "coding",
          model: "Owner/DeepSeek",
          source: "task",
          reason: "task_model",
          available: true,
        }}
        onShowProgress={onShowProgress}
        onContinueChat={onContinueChat}
      />
    </I18nextProvider>,
  );
  expect(screen.getByRole("status")).toHaveTextContent("运行 Python 命令");
  expect(screen.queryByText(/opaque script/)).not.toBeInTheDocument();
  expect(
    screen.queryByText("可以继续补充消息，也可以随时上传文件"),
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: zh.chat.backgroundUi.progress }),
  );
  expect(onShowProgress).toHaveBeenCalledOnce();
  fireEvent.click(
    screen.getByRole("button", { name: zh.chat.flow.anotherChat }),
  );
  expect(onContinueChat).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: /本次模型选择/ }));
  expect(await screen.findByText(/Owner\/DeepSeek/)).toBeInTheDocument();
  expect(
    await screen.findByText(zh.modelRouting.reasons.task_model),
  ).toBeInTheDocument();
});
