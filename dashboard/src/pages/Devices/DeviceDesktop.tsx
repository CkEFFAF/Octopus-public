import { useEffect, useRef, useState } from "react";
import { Alert, Button, Input, Select, Switch } from "antd";
import { ArrowDown, ArrowUp, Eye, MousePointer2, Square } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  devicesApi,
  type Device,
  type DeviceInput,
} from "../../api/modules/devices";
import { canUse, desktopPoint } from "./helpers";
import {
  executionApi,
  type ExecutionContext,
  type ExecutionTarget,
} from "../../api/modules/execution";
import styles from "./DeviceDesktop.module.less";

type Props = {
  device: Device | ExecutionTarget;
  onError: (error: unknown) => void;
  context?: ExecutionContext;
  visible?: boolean;
};

export default function DeviceDesktop(props: Props) {
  return (
    <DesktopSession
      key={`${props.device.device_id}:${props.context?.context_id ?? "device"}`}
      {...props}
    />
  );
}

function DesktopSession({ device, onError, context, visible = true }: Props) {
  const { t } = useTranslation();
  const [viewing, setViewing] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [frame, setFrame] = useState<{
    jpeg_b64: string;
    width: number;
    height: number;
    left?: number;
    top?: number;
  } | null>(null);
  const [text, setText] = useState("");
  const [key, setKey] = useState("enter");
  const [button, setButton] = useState<"left" | "right">("left");
  const [inputBusy, setInputBusy] = useState(false);
  const inputPending = useRef(false);
  const pointerStart = useRef<{ x: number; y: number } | null>(null);
  const lastPoint = useRef<{ x: number; y: number } | null>(null);
  const reportError = useRef(onError);
  reportError.current = onError;
  const alive = useRef(true);
  const inputController = useRef<AbortController | null>(null);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      inputController.current?.abort();
    };
  }, []);
  const viewAllowed = canUse(device, "desktop_view");
  const executionContextId = context?.context_id;
  const controlAllowed =
    canUse(device, "desktop_control") &&
    context?.work_mode !== "plan" &&
    context?.work_mode !== "ask";
  const inputEnabled =
    visible && viewing && controlling && controlAllowed && Boolean(frame);

  useEffect(() => {
    if (!viewAllowed) {
      setViewing(false);
      setControlling(false);
      setFrame(null);
    } else if (!controlAllowed) {
      setControlling(false);
    }
  }, [viewAllowed, controlAllowed]);

  useEffect(() => {
    if (!visible || !viewing || !viewAllowed) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    const capture = async () => {
      if (!active) return;
      if (document.hidden) {
        timer = setTimeout(capture, 1000);
        return;
      }
      controller = new AbortController();
      const timeout = setTimeout(() => controller?.abort(), 20000);
      try {
        const next = executionContextId
          ? await executionApi.call<NonNullable<typeof frame>>(
              executionContextId,
              "desktop.capture",
              { quality: 65 },
              controller.signal,
            )
          : await devicesApi.call(
              device.device_id ?? "",
              "desktop.capture",
              { quality: 65 },
              controller.signal,
            );
        if (active) setFrame(next);
      } catch (error) {
        if (active) {
          reportError.current(error);
          setViewing(false);
          setControlling(false);
          setFrame(null);
        }
        active = false;
      } finally {
        clearTimeout(timeout);
        if (active) timer = setTimeout(capture, 1000);
      }
    };
    void capture();
    return () => {
      active = false;
      clearTimeout(timer);
      controller?.abort();
    };
  }, [executionContextId, device.device_id, viewAllowed, viewing, visible]);

  async function input(params: DeviceInput) {
    if (!inputEnabled || inputPending.current) return;
    inputPending.current = true;
    setInputBusy(true);
    const controller = new AbortController();
    inputController.current = controller;
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      if (context)
        await executionApi.call(
          context.context_id,
          "desktop.input",
          { ...params },
          controller.signal,
        );
      else
        await devicesApi.call(
          device.device_id ?? "",
          "desktop.input",
          params,
          controller.signal,
        );
      if (alive.current && params.kind === "type") setText("");
    } catch (error) {
      if (alive.current) {
        onError(error);
        setControlling(false);
      }
    } finally {
      clearTimeout(timeout);
      inputPending.current = false;
      inputController.current = null;
      if (alive.current) setInputBusy(false);
    }
  }

  function scroll(dy: number) {
    if (!frame) return;
    const point = lastPoint.current ?? {
      x: (frame.left ?? 0) + Math.floor(frame.width / 2),
      y: (frame.top ?? 0) + Math.floor(frame.height / 2),
    };
    void input({ kind: "scroll", ...point, dy });
  }

  return (
    <div className={styles.root}>
      <Alert type="info" showIcon message={t("devices.desktopHint")} />
      <div className={styles.actions}>
        <Button
          icon={
            viewing && viewAllowed ? <Square size={16} /> : <Eye size={16} />
          }
          disabled={!viewAllowed}
          onClick={() => {
            setViewing(!viewing);
            setFrame(null);
            lastPoint.current = null;
            setControlling(false);
          }}
        >
          {t(
            viewing && viewAllowed
              ? "devices.stopViewing"
              : "devices.startViewing",
          )}
        </Button>
        <label className={styles.control}>
          <MousePointer2 size={16} />
          {t("devices.enableInput")}
          <Switch
            checked={controlling && controlAllowed && viewing}
            disabled={!controlAllowed || !viewing}
            onChange={setControlling}
          />
        </label>
      </div>
      <div
        className={`${styles.screen} devices-screen`}
        aria-label={t("devices.desktopScreen")}
      >
        {frame && viewing && viewAllowed ? (
          <img
            src={`data:image/jpeg;base64,${frame.jpeg_b64}`}
            alt={t("devices.desktopOf", { name: device.name })}
            draggable={false}
            style={{ cursor: inputEnabled ? "crosshair" : "default" }}
            onContextMenu={(event) => event.preventDefault()}
            onPointerDown={(event) => {
              pointerStart.current = { x: event.clientX, y: event.clientY };
            }}
            onPointerCancel={() => {
              pointerStart.current = null;
            }}
            onPointerUp={(event) => {
              const start = pointerStart.current;
              pointerStart.current = null;
              if (
                !start ||
                Math.hypot(event.clientX - start.x, event.clientY - start.y) > 8
              )
                return;
              const point = desktopPoint(
                event.clientX,
                event.clientY,
                event.currentTarget.getBoundingClientRect(),
                frame,
              );
              if (point) {
                lastPoint.current = point;
                void input({ kind: "click", ...point, button });
              }
            }}
          />
        ) : (
          <span>
            {t(
              viewing && viewAllowed
                ? "devices.waitingFrame"
                : "devices.screenStopped",
            )}
          </span>
        )}
      </div>
      <p className={styles.hint}>{t("devices.touchHint")}</p>
      <div className={styles.actions}>
        <Select
          aria-label={t("devices.mouseButton")}
          value={button}
          onChange={setButton}
          options={["left", "right"].map((value) => ({
            value,
            label: t(`devices.${value}Click`),
          }))}
        />
        <Button
          disabled={!inputEnabled || inputBusy}
          icon={<ArrowUp size={16} />}
          onClick={() => scroll(-120)}
        >
          {t("devices.scrollUp")}
        </Button>
        <Button
          disabled={!inputEnabled || inputBusy}
          icon={<ArrowDown size={16} />}
          onClick={() => scroll(120)}
        >
          {t("devices.scrollDown")}
        </Button>
      </div>
      <label className={styles.field}>
        <span>{t("devices.typeText")}</span>
        <Input.TextArea
          value={text}
          onChange={(event) => setText(event.target.value)}
          autoSize={{ minRows: 2, maxRows: 5 }}
          disabled={!inputEnabled}
        />
      </label>
      <div className={styles.actions}>
        <Button
          disabled={!inputEnabled || inputBusy || !text}
          loading={inputBusy}
          onClick={() => void input({ kind: "type", text })}
        >
          {t("devices.sendText")}
        </Button>
        <Select
          aria-label={t("devices.keyboardKey")}
          value={key}
          onChange={setKey}
          options={[
            "enter",
            "esc",
            "tab",
            "backspace",
            "up",
            "down",
            "left",
            "right",
            "ctrl+c",
            "ctrl+v",
            "ctrl+a",
          ].map((value) => ({ value, label: value }))}
        />
        <Button
          disabled={!inputEnabled || inputBusy}
          onClick={() => void input({ kind: "key", key })}
        >
          {t("devices.sendKey")}
        </Button>
      </div>
    </div>
  );
}
