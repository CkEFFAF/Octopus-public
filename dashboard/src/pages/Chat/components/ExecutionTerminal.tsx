import { useCallback, useEffect, useRef, useState } from "react";
import { Alert } from "antd";
import { useTranslation } from "react-i18next";
import {
  executionApi,
  type ExecutionContext,
} from "../../../api/modules/execution";
import TerminalView, {
  type TerminalViewHandle,
} from "../../Control/Terminal/components/TerminalView";
import {
  getTerminalTheme,
  TERMINAL_THEME_STORAGE_KEY,
} from "../../Control/Terminal/terminalThemes";
import { base64ToBytes, bytesToBase64 } from "../../Devices/helpers";
import styles from "./ExecutionWorkbench.module.less";

interface Poll {
  data_b64: string;
  next_offset: number;
  eof: boolean;
  gap: boolean;
  returncode: number | null;
  error: string | null;
}

export default function ExecutionTerminal({
  context,
  visible,
}: {
  context: ExecutionContext;
  visible: boolean;
}) {
  const { t } = useTranslation();
  const terminal = useRef<TerminalViewHandle | null>(null);
  const [sessionId] = useState(() =>
    Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) =>
      value.toString(16).padStart(2, "0"),
    ).join(""),
  );
  const [ready, setReady] = useState(false);
  const [connected, setConnected] = useState(false);
  const [ended, setEnded] = useState(false);
  const [error, setError] = useState("");
  const [inputFailure, setInputFailure] = useState("");
  const inputBlocked = useRef(false);
  const opening = useRef<Promise<unknown> | null>(null);
  const mounted = useRef(false);
  const input = useRef("");
  const inputTimer = useRef<ReturnType<typeof setTimeout>>();
  const resizeTimer = useRef<ReturnType<typeof setTimeout>>();
  const writes = useRef(Promise.resolve());
  const offset = useRef(0);
  const decoder = useRef(new TextDecoder());
  const theme = getTerminalTheme(
    localStorage.getItem(TERMINAL_THEME_STORAGE_KEY),
    true,
  );
  useEffect(() => {
    if (!ready) return;
    mounted.current = true;
    opening.current ??= executionApi.call(context.context_id, "terminal.open", {
      session_id: sessionId,
      cols: 80,
      rows: 24,
    });
    void opening.current
      .then(() => {
        if (mounted.current) {
          setConnected(true);
          terminal.current?.fit();
        }
      })
      .catch((failure) => {
        if (mounted.current) setError(String(failure));
      });
    return () => {
      mounted.current = false;
      clearTimeout(inputTimer.current);
      clearTimeout(resizeTimer.current);
      // React StrictMode may immediately attach the same component again.
      setTimeout(() => {
        if (!mounted.current)
          void opening.current
            ?.then(() =>
              executionApi.call(context.context_id, "terminal.close", {
                session_id: sessionId,
              }),
            )
            .catch(() => undefined);
      }, 0);
    };
  }, [ready, context.context_id, sessionId]);
  useEffect(() => {
    if (!connected || !visible || ended) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await executionApi.call<Poll>(
          context.context_id,
          "terminal.poll",
          { session_id: sessionId, offset: offset.current },
        );
        if (disposed) return;
        if (value.gap)
          terminal.current?.write(
            `\r\n[${t("chat.execution.terminalGap")}]\r\n`,
          );
        offset.current = value.next_offset;
        terminal.current?.write(
          decoder.current.decode(base64ToBytes(value.data_b64), {
            stream: !value.eof,
          }),
        );
        setError(value.error ?? "");
        if (value.eof) {
          setEnded(true);
          terminal.current?.write(
            `\r\n[${t("chat.execution.exitCode")} ${
              value.returncode ?? "?"
            }]\r\n`,
          );
          return;
        }
      } catch (failure) {
        if (!disposed) setError(String(failure));
      }
      if (!disposed) timer = setTimeout(() => void poll(), 150);
    }
    void poll();
    terminal.current?.fit();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [context.context_id, sessionId, connected, visible, ended, t]);
  const onData = useCallback(
    (data: string) => {
      if (!connected || ended || error || inputBlocked.current) return;
      input.current += data;
      clearTimeout(inputTimer.current);
      inputTimer.current = setTimeout(() => {
        const characters = [...input.current];
        input.current = "";
        for (let index = 0; index < characters.length; index += 1024) {
          const data_b64 = bytesToBase64(
            new TextEncoder().encode(
              characters.slice(index, index + 1024).join(""),
            ),
          );
          writes.current = writes.current
            .then(async () => {
              if (!mounted.current || inputBlocked.current) return;
              await executionApi.call(context.context_id, "terminal.input", {
                session_id: sessionId,
                data_b64,
              });
            })
            .catch((failure) => {
              inputBlocked.current = true;
              input.current = "";
              clearTimeout(inputTimer.current);
              if (mounted.current) {
                setError(String(failure));
                setInputFailure(t("chat.execution.inputUnknown"));
              }
            });
        }
      }, 25);
    },
    [connected, ended, error, context.context_id, sessionId, t],
  );
  const onResize = useCallback(
    (cols: number, rows: number) => {
      if (!connected || ended) return;
      clearTimeout(resizeTimer.current);
      resizeTimer.current = setTimeout(() => {
        void executionApi
          .call(context.context_id, "terminal.resize", {
            session_id: sessionId,
            cols: Math.min(500, Math.max(2, cols)),
            rows: Math.min(200, Math.max(2, rows)),
          })
          .catch((failure) => {
            if (mounted.current) setError(String(failure));
          });
      }, 100);
    },
    [connected, ended, context.context_id, sessionId],
  );
  return (
    <div className={styles.terminal}>
      {error && <Alert type="error" message={error} />}
      {inputFailure && <Alert type="warning" message={inputFailure} />}
      <TerminalView
        terminalRef={terminal}
        themeDefinition={theme}
        onReady={() => setReady(true)}
        onData={onData}
        onResize={onResize}
      />
    </div>
  );
}
