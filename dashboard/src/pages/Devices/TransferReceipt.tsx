import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Progress } from "antd";
import { useTranslation } from "react-i18next";
import { devicesApi, type DeviceTransfer } from "../../api/modules/devices";
import { formatBytes } from "./helpers";
import styles from "./TransferReceipt.module.less";

export default function TransferReceipt({
  initial,
}: {
  initial: DeviceTransfer;
}) {
  const { t } = useTranslation();
  const [state, setState] = useState(initial);
  const [stale, setStale] = useState(false);
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    try {
      setState(await devicesApi.transferStatus(initial.transfer_id));
      setStale(false);
    } catch {
      setStale(true);
    }
  }, [initial.transfer_id]);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!document.hidden) await refresh();
      if (active) timer = setTimeout(poll, 2000);
    };
    void poll();
    const recover = () => {
      if (!document.hidden) void refresh();
    };
    window.addEventListener("online", recover);
    window.addEventListener("focus", recover);
    document.addEventListener("visibilitychange", recover);
    return () => {
      active = false;
      clearTimeout(timer);
      window.removeEventListener("online", recover);
      window.removeEventListener("focus", recover);
      document.removeEventListener("visibilitychange", recover);
    };
  }, [refresh]);
  const complete =
    state.status === "completed" &&
    state.receipts.source &&
    state.receipts.target;
  const direct =
    state.actual_transport === "direct" &&
    ["transferring", "completed"].includes(state.status);
  const terminal = [
    "completed",
    "failed",
    "cancelled",
    "expired",
    "unknown",
  ].includes(state.status);
  const label =
    state.status === "completed" && !complete
      ? "pending_receipt"
      : state.status;
  return (
    <section className={styles.receipt} aria-label={t("devices.p2p.receipt")}>
      <div className={styles.heading}>
        <strong>
          {t(`devices.p2p.status.${label}`, { defaultValue: label })}
        </strong>
        <span>
          {t(
            direct
              ? "devices.p2p.direct"
              : state.actual_transport === "hub"
              ? "devices.p2p.hub"
              : "devices.p2p.unconfirmed",
          )}
        </span>
      </div>
      <p>
        {formatBytes(state.bytes_done)}
        {state.bytes_total != null
          ? ` / ${formatBytes(state.bytes_total)}`
          : ""}
      </p>
      {state.bytes_total != null && state.bytes_total > 0 && (
        <Progress
          percent={
            complete
              ? 100
              : Math.min(
                  99,
                  Math.floor((state.bytes_done / state.bytes_total) * 100),
                )
          }
          status={complete ? "success" : "normal"}
          strokeColor="var(--fn-color-primary)"
        />
      )}
      {state.fallback_reason && (
        <Alert
          type="info"
          showIcon
          message={t("devices.p2p.fallback", {
            reason: t(`apiErrors.${state.fallback_reason}`, {
              defaultValue: state.fallback_reason,
            }),
          })}
        />
      )}
      {state.error_code && (
        <Alert
          type="warning"
          showIcon
          message={t(`apiErrors.${state.error_code}`, {
            defaultValue: state.error_code,
          })}
          description={
            state.failure_direction
              ? t(`devices.p2p.direction.${state.failure_direction}`, {
                  defaultValue: state.failure_direction,
                })
              : undefined
          }
        />
      )}
      <p className={styles.audit}>
        {t("devices.p2p.audit")} <code>{state.audit_id}</code>
      </p>
      {stale && (
        <Alert
          type="warning"
          message={t("devices.p2p.stale")}
          action={
            <Button size="small" onClick={() => void refresh()}>
              {t("common.retry")}
            </Button>
          }
        />
      )}
      {!terminal && (
        <Button
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              setState(await devicesApi.cancelTransfer(state.transfer_id));
              setStale(false);
            } catch {
              setStale(true);
            } finally {
              setBusy(false);
            }
          }}
        >
          {t("devices.cancelOperation")}
        </Button>
      )}
    </section>
  );
}
