import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button } from "antd";
import { useTranslation } from "react-i18next";
import {
  executionApi,
  type ExecutionContext,
} from "../../../api/modules/execution";
import BrowserViewer, {
  type BrowserViewerHandle,
} from "../../../components/BrowserViewer";
import type { BrowserTab } from "../../../hooks/useBrowserStream";
import styles from "./ExecutionWorkbench.module.less";

interface BrowserState {
  session_id: string;
  tabs: BrowserTab[];
  data_b64?: string;
}

export default function ExecutionBrowser({
  context,
  visible,
}: {
  context: ExecutionContext;
  visible: boolean;
}) {
  const { t } = useTranslation();
  const viewer = useRef<BrowserViewerHandle>(null);
  const [tabs, setTabs] = useState<BrowserTab[]>([]);
  const [navUrl, setNavUrl] = useState("");
  const [connected, setConnected] = useState(false);
  const [frame, setFrame] = useState("");
  const [error, setError] = useState("");
  const [inputFailure, setInputFailure] = useState(false);
  const [retry, setRetry] = useState(0);
  const halted = useRef(true);
  const generation = useRef(0);
  const writes = useRef(Promise.resolve());
  const pending = useRef(0);
  const applyState = useCallback((value: BrowserState) => {
    setTabs(value.tabs);
  }, []);
  const activeUrl = tabs.find((tab) => tab.active)?.url ?? "";
  useEffect(
    () => setNavUrl(activeUrl === "about:blank" ? "" : activeUrl),
    [activeUrl],
  );

  useEffect(() => {
    const lifecycleGeneration = generation;
    const current = ++lifecycleGeneration.current;
    halted.current = true;
    setConnected(false);
    setFrame("");
    setError("");
    // Opening reattaches to this expert/thread on the original device. It
    // does not navigate again or replay an input whose receipt was lost.
    void writes.current
      .then(async () => {
        if (generation.current !== current) return;
        const value = await executionApi.call<BrowserState>(
          context.context_id,
          "browser.open",
          {},
        );
        if (generation.current !== current) return;
        if (retry > 0 && value.tabs.length) {
          await executionApi.call(context.context_id, "browser.action", {
            command: "reset_input",
          });
        }
        if (generation.current !== current) return;
        applyState(value);
        halted.current = false;
        setInputFailure(false);
        setConnected(true);
      })
      .catch((failure) => {
        if (generation.current === current) setError(String(failure));
      });
    return () => {
      lifecycleGeneration.current++;
      halted.current = true;
    };
  }, [context.context_id, retry, applyState]);

  useEffect(() => {
    if (!connected || !visible || !tabs.length) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const abort = new AbortController();
    async function capture() {
      if (disposed) return;
      if (document.visibilityState === "hidden") {
        timer = setTimeout(() => void capture(), 1000);
        return;
      }
      try {
        const value = await executionApi.call<BrowserState>(
          context.context_id,
          "browser.capture",
          {},
          abort.signal,
        );
        if (disposed) return;
        setTabs(value.tabs);
        if (value.data_b64) setFrame(value.data_b64);
      } catch (failure) {
        if (disposed) return;
        halted.current = true;
        setError(String(failure));
        setConnected(false);
        return;
      }
      timer = setTimeout(() => void capture(), 500);
    }
    void capture();
    return () => {
      disposed = true;
      clearTimeout(timer);
      abort.abort();
    };
  }, [context.context_id, connected, visible, tabs.length]);

  useEffect(() => {
    if (frame && !error) viewer.current?.paintFrame(frame);
  }, [frame, error]);

  const send = useCallback(
    (command: string, params: Record<string, unknown> = {}) => {
      if (!connected || !visible || halted.current) return false;
      // Hover may be coalesced; presses, releases, typing and navigation retain
      // their order. A lost receipt stops the whole queue until manual reconnect.
      if (command === "mousemove" && !params.buttons && pending.current > 1)
        return true;
      if (pending.current >= 64) {
        halted.current = true;
        setInputFailure(true);
        return false;
      }
      const current = generation.current;
      pending.current++;
      writes.current = writes.current
        .then(async () => {
          if (generation.current !== current || halted.current) return;
          const value = await executionApi.call<BrowserState>(
            context.context_id,
            "browser.action",
            { ...params, command },
          );
          if (generation.current === current) applyState(value);
        })
        .catch((failure) => {
          if (generation.current !== current) return;
          halted.current = true;
          setInputFailure(true);
          setError(String(failure));
        })
        .finally(() => {
          pending.current--;
        });
      return true;
    },
    [context.context_id, connected, visible, applyState],
  );

  const sendEvent = useCallback(
    (event: Record<string, unknown>) => {
      const type = String(event.type);
      const command =
        (
          {
            goback: "go_back",
            goforward: "go_forward",
            keydown: "press",
          } as Record<string, string>
        )[type] ?? type;
      return send(command, event);
    },
    [send],
  );

  return (
    <div className={styles.browser}>
      {error && <Alert type="error" message={error} />}
      {inputFailure && (
        <Alert
          type="warning"
          message={t("chat.execution.browserInputUnknown")}
          action={
            <Button size="small" onClick={() => setRetry((value) => value + 1)}>
              {t("browserViewer.reconnect")}
            </Button>
          }
        />
      )}
      <BrowserViewer
        ref={viewer}
        status={error ? "error" : connected ? "streaming" : "connecting"}
        tabs={tabs}
        navUrl={navUrl}
        onNavUrlChange={setNavUrl}
        onNavigate={(url) => send("navigate", { url })}
        switchTab={(tab_id) => send("switch_tab", { tab_id })}
        closeTab={(tab_id) => send("close_tab", { tab_id })}
        newTab={() => send("new_tab", { url: "about:blank" })}
        sendEvent={sendEvent}
        interactive={connected && visible && !error && !inputFailure}
        connectingHint={t("chat.execution.browserHint")}
        onReconnect={() => setRetry((value) => value + 1)}
        onCanvasKeyDown={(event) => {
          if (
            event.nativeEvent.isComposing ||
            ["Control", "Shift", "Alt", "Meta"].includes(event.key)
          )
            return;
          if (
            (event.ctrlKey || event.metaKey) &&
            event.key.toLowerCase() === "v"
          )
            return;
          event.preventDefault();
          const modifiers = [
            event.ctrlKey && "Control",
            event.metaKey && "Meta",
            event.altKey && "Alt",
            event.shiftKey && "Shift",
          ].filter(Boolean);
          if (
            event.key.length === 1 &&
            !event.ctrlKey &&
            !event.metaKey &&
            !event.altKey
          )
            send("type", { text: event.key });
          else
            send("press", {
              key: [...modifiers, event.key === " " ? "Space" : event.key].join(
                "+",
              ),
            });
        }}
        onCanvasPaste={(event) => {
          event.preventDefault();
          send("type", { text: event.clipboardData.getData("text") });
        }}
        onCanvasCompositionEnd={(event) => {
          if (event.data) send("type", { text: event.data });
        }}
      />
    </div>
  );
}
