import { useEffect, useRef, useState } from "react";
import { Alert, Button, Input, Modal, Progress, Select } from "antd";
import { Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import { devicesApi } from "../../api/modules/devices";
import {
  executionApi,
  type ExecutionContext,
} from "../../api/modules/execution";
import { LOCAL_TARGET, targetFields } from "../Chat/hooks/deviceTarget";
import {
  copyNativeFile,
  downloadNativeFile,
  uploadNativeFile,
  NativeTransferError,
} from "./nativeTransfers";
import { formatBytes } from "./helpers";

export interface TransferSelection {
  path: string;
  name: string;
  action: "download" | "copy";
}
interface FileWriter {
  write: (data: Uint8Array) => Promise<void>;
  close: () => Promise<void>;
  abort: () => Promise<void>;
}
type SaveWindow = Window & {
  showSaveFilePicker?: (options: {
    suggestedName: string;
  }) => Promise<{ createWritable: () => Promise<FileWriter> }>;
};

export default function NativeFileTransfers({
  context,
  directory,
  writable,
  selection,
  clearSelection,
  onError,
  onChanged,
}: {
  context: ExecutionContext;
  directory: string;
  writable: boolean;
  selection: TransferSelection | null;
  clearSelection: () => void;
  onError: (error: unknown) => void;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const uploadInput = useRef<HTMLInputElement | null>(null);
  const active = useRef<AbortController | null>(null);
  const alive = useRef(true);
  const [progress, setProgress] = useState<{
    done: number;
    total: number;
  } | null>(null);
  const [target, setTarget] = useState("");
  const [destination, setDestination] = useState("");
  const [choices, setChoices] = useState<
    { value: string; label: string; disabled?: boolean }[]
  >([]);
  const [receipt, setReceipt] = useState("");
  const [download, setDownload] = useState<{
    url: string;
    name: string;
  } | null>(null);
  const downloadUrl = useRef("");
  const selectionKey = selection ? `${selection.action}:${selection.path}` : "";
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      active.current?.abort();
      if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current);
    };
  }, []);
  useEffect(() => {
    if (selection?.action !== "copy") return;
    let disposed = false;
    setDestination(selection.name);
    setTarget("");
    void Promise.all([devicesApi.list(), executionApi.localAvailable()])
      .then(([value, local]) => {
        if (!disposed)
          setChoices([
            ...(local.available
              ? [{ value: LOCAL_TARGET, label: t("devices.localExecution") }]
              : []),
            ...value.devices
              .filter((item) => item.revoked_at === null)
              .map((item) => ({
                value: item.device_id,
                label: item.name,
                disabled:
                  !item.online ||
                  !item.permissions.includes("files_write") ||
                  item.runtime?.transfer_protocol_version !== 1,
              })),
          ]);
      })
      .catch((error) => {
        if (!disposed) onError(error);
      });
    return () => {
      disposed = true;
    };
    // The operation keeps the context and file selected when its menu was opened.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectionKey]);

  async function perform(
    task: (
      signal: AbortSignal,
      report: (done: number, total: number) => void,
    ) => Promise<unknown>,
  ) {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setReceipt("");
    setProgress({ done: 0, total: 0 });
    try {
      await task(controller.signal, (done, total) => {
        if (alive.current) setProgress({ done, total });
      });
      if (alive.current) {
        setReceipt(t("devices.native.transferVerified"));
        onChanged();
      }
    } catch (error) {
      if (alive.current) {
        if (
          controller.signal.aborted ||
          (error instanceof DOMException && error.name === "AbortError")
        )
          setReceipt(t("devices.browserCancelled"));
        else
          onError(
            error instanceof NativeTransferError
              ? new Error(t(error.key))
              : error,
          );
      }
    } finally {
      active.current = null;
      if (alive.current) {
        setProgress(null);
        clearSelection();
      }
    }
  }

  function saveSelected() {
    if (!selection) return;
    const chosen = selection;
    // Open the browser picker directly in the user's click handler.
    const picker = (window as SaveWindow).showSaveFilePicker;
    const writer = picker
      ? picker
          .call(window, { suggestedName: chosen.name })
          .then((handle) => handle.createWritable())
      : Promise.resolve(undefined);
    void perform(async (signal, report) => {
      const sink = await writer;
      if (signal.aborted) {
        await sink?.abort();
        signal.throwIfAborted();
      }
      const blob = await downloadNativeFile(
        context.context_id,
        chosen.path,
        signal,
        report,
        sink,
      );
      if (blob && alive.current) {
        if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current);
        downloadUrl.current = URL.createObjectURL(blob);
        setDownload({ url: downloadUrl.current, name: chosen.name });
      }
    });
  }

  return (
    <>
      <input
        ref={uploadInput}
        type="file"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) return;
          const path = `${directory.replace(/[\\/]$/, "")}/${file.name}`;
          void perform((signal, report) =>
            uploadNativeFile(context.context_id, path, file, signal, report),
          );
        }}
      />
      <Button
        size="small"
        icon={<Upload size={15} />}
        disabled={!writable || Boolean(progress)}
        onClick={() => uploadInput.current?.click()}
      >
        {t("devices.upload")}
      </Button>
      {progress && (
        <div style={{ minWidth: 140 }}>
          <Progress
            size="small"
            percent={
              progress.total
                ? Math.floor((progress.done * 100) / progress.total)
                : 0
            }
          />
          <small>
            {formatBytes(progress.done)} / {formatBytes(progress.total)}{" "}
          </small>
          <Button
            size="small"
            type="text"
            onClick={() => active.current?.abort()}
          >
            {t("common.cancel")}
          </Button>
        </div>
      )}
      {receipt && <span role="status">{receipt}</span>}
      {download && (
        <a href={download.url} download={download.name}>
          {t("devices.download")} · {download.name}
        </a>
      )}
      <Modal
        open={Boolean(selection)}
        title={t(
          selection?.action === "copy"
            ? "devices.native.copyTo"
            : "devices.download",
        )}
        onCancel={() => {
          active.current?.abort();
          if (!active.current) clearSelection();
        }}
        onOk={() => {
          if (!selection || progress) return;
          if (selection.action === "download") {
            saveSelected();
            return;
          }
          const chosen = selection;
          void perform(async (signal, report) => {
            const targetContext = await executionApi.createContext({
              ...targetFields(target),
              work_mode: context.work_mode,
            });
            signal.throwIfAborted();
            await copyNativeFile(
              context.context_id,
              chosen.path,
              targetContext.context_id,
              destination,
              signal,
              report,
            );
          });
        }}
        confirmLoading={Boolean(progress)}
        okButtonProps={{
          disabled:
            Boolean(progress) ||
            (selection?.action === "copy" && (!target || !destination.trim())),
        }}
      >
        <p>
          <code>{selection?.path}</code>
        </p>
        {selection?.action === "copy" ? (
          <>
            <Select
              aria-label={t("devices.targetDevice")}
              placeholder={t("devices.noTarget")}
              value={target || undefined}
              onChange={setTarget}
              options={choices}
              style={{ width: "100%", marginBottom: 12 }}
            />
            <Input
              aria-label={t("devices.native.path")}
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
            />
          </>
        ) : (
          <Alert type="info" message={t("devices.native.downloadHint")} />
        )}
      </Modal>
    </>
  );
}
