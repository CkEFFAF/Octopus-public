import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Empty, Input, Progress, Select } from "antd";
import {
  ArrowUp,
  Download,
  File,
  Folder,
  RefreshCw,
  Upload,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  devicesApi,
  type Device,
  type DeviceFileEntry,
  type DeviceOperation,
} from "../../api/modules/devices";
import {
  base64ToBytes,
  bytesToBase64,
  canUse,
  formatBytes,
  joinPath,
  parentPath,
  sha256,
} from "./helpers";
import NativeDeviceFiles from "./NativeDeviceFiles";

const CHUNK_SIZE = 1024 * 1024;

export default function DeviceFiles({
  device,
  devices,
  onError,
  onOperation,
}: {
  device: Device;
  devices: Device[];
  onError: (error: unknown) => void;
  onOperation: (operation: DeviceOperation) => void;
}) {
  return device.trust_mode === "owner" ? (
    <NativeDeviceFiles device={device} onError={onError} />
  ) : (
    <RestrictedDeviceFiles
      device={device}
      devices={devices}
      onError={onError}
      onOperation={onOperation}
    />
  );
}

function RestrictedDeviceFiles({
  device,
  devices,
  onError,
  onOperation,
}: {
  device: Device;
  devices: Device[];
  onError: (error: unknown) => void;
  onOperation: (operation: DeviceOperation) => void;
}) {
  const { t } = useTranslation();
  const [rootId, setRootId] = useState(device.roots[0]?.id ?? "");
  const [path, setPath] = useState("");
  const [entries, setEntries] = useState<DeviceFileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<{
    name: string;
    direction: "upload" | "download";
    done: number;
    total: number;
  } | null>(null);
  const [localResult, setLocalResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);
  const [download, setDownload] = useState<{
    url: string;
    name: string;
  } | null>(null);
  const [targetId, setTargetId] = useState("");
  const [targetRootId, setTargetRootId] = useState("");
  const [sourcePath, setSourcePath] = useState("");
  const [targetPath, setTargetPath] = useState("");
  const [transferBusy, setTransferBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const downloadUrl = useRef("");
  const root = device.roots.find((item) => item.id === rootId);
  const readable = Boolean(root?.read && canUse(device, "files_read"));
  const writable = Boolean(root?.write && canUse(device, "files_write"));
  const targets = devices.filter(
    (item) =>
      item.device_id !== device.device_id &&
      canUse(item, "files_write") &&
      item.roots.some((item) => item.write),
  );
  const target = targets.find((item) => item.device_id === targetId);
  const targetRoot = target?.roots.find(
    (item) => item.id === targetRootId && item.write,
  );
  const reportError = useRef(onError);
  reportError.current = onError;

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!readable) {
        setEntries([]);
        return;
      }
      setLoading(true);
      try {
        const result = await devicesApi.call(
          device.device_id,
          "files.list",
          { root_id: rootId, path },
          signal,
        );
        if (!signal?.aborted) setEntries(result.entries);
      } catch (error) {
        if (!signal?.aborted) reportError.current(error);
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [device.device_id, path, readable, rootId],
  );

  useEffect(() => {
    const abort = new AbortController();
    void load(abort.signal);
    return () => abort.abort();
  }, [load]);

  useEffect(
    () => () => {
      controller.current?.abort();
      if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current);
    },
    [],
  );

  async function upload(file: globalThis.File) {
    if (!writable || controller.current) return;
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setLocalResult(null);
    setProgress({
      name: file.name,
      direction: "upload",
      done: 0,
      total: file.size,
    });
    let uploadId = "";
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      const hash = await sha256(bytes);
      abort.signal.throwIfAborted();
      const begun = await devicesApi.call(
        device.device_id,
        "files.write_begin",
        {
          root_id: rootId,
          path: joinPath(path, file.name),
          size: file.size,
          sha256: hash,
        },
        abort.signal,
      );
      uploadId = begun.upload_id;
      for (let offset = 0; offset < bytes.length; offset += CHUNK_SIZE) {
        const chunk = bytes.subarray(offset, offset + CHUNK_SIZE);
        const result = await devicesApi.call(
          device.device_id,
          "files.write_chunk",
          {
            upload_id: uploadId,
            offset,
            data_b64: bytesToBase64(chunk),
          },
          abort.signal,
        );
        if (result.bytes_done !== offset + chunk.length)
          throw new Error(t("devices.chunkMismatch"));
        setProgress({
          name: file.name,
          direction: "upload",
          done: result.bytes_done,
          total: file.size,
        });
      }
      const committed = await devicesApi.call(
        device.device_id,
        "files.write_commit",
        { upload_id: uploadId },
        abort.signal,
      );
      if (committed.sha256 !== hash || committed.size !== file.size)
        throw new Error(t("devices.checksumMismatch"));
      uploadId = "";
      setLocalResult({
        success: true,
        message: t("devices.uploadVerified", { name: file.name }),
      });
      setProgress(null);
      await load();
    } catch (error) {
      if (uploadId) {
        try {
          await devicesApi.call(device.device_id, "files.write_abort", {
            upload_id: uploadId,
          });
        } catch (abortError) {
          reportError.current(abortError);
        }
      }
      if (!abort.signal.aborted) onError(error);
      if (abort.signal.aborted)
        setLocalResult({
          success: false,
          message: t("devices.browserCancelled"),
        });
      setProgress(null);
    } finally {
      controller.current = null;
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function prepareDownload(entry: DeviceFileEntry) {
    if (!readable || controller.current) return;
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setLocalResult(null);
    setProgress({
      name: entry.name,
      direction: "download",
      done: 0,
      total: entry.size,
    });
    if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current);
    downloadUrl.current = "";
    setDownload(null);
    try {
      const stat = await devicesApi.call(
        device.device_id,
        "files.stat",
        { root_id: rootId, path: entry.path },
        abort.signal,
      );
      const bytes = new Uint8Array(stat.size);
      let offset = 0;
      do {
        const result = await devicesApi.call(
          device.device_id,
          "files.read",
          { root_id: rootId, path: entry.path, offset, length: CHUNK_SIZE },
          abort.signal,
        );
        const chunk = base64ToBytes(result.data_b64);
        if (
          result.offset !== offset ||
          result.size !== stat.size ||
          offset + chunk.length > stat.size ||
          (!result.eof && offset + chunk.length === stat.size) ||
          (!result.eof && !chunk.length)
        )
          throw new Error(t("devices.chunkMismatch"));
        bytes.set(chunk, offset);
        offset += chunk.length;
        setProgress({
          name: entry.name,
          direction: "download",
          done: offset,
          total: stat.size,
        });
        if (result.eof) break;
      } while (offset < stat.size);
      if (offset !== stat.size || (await sha256(bytes)) !== stat.sha256)
        throw new Error(t("devices.checksumMismatch"));
      abort.signal.throwIfAborted();
      downloadUrl.current = URL.createObjectURL(new Blob([bytes]));
      setDownload({ url: downloadUrl.current, name: entry.name });
      setProgress(null);
    } catch (error) {
      if (!abort.signal.aborted) onError(error);
      if (abort.signal.aborted)
        setLocalResult({
          success: false,
          message: t("devices.browserCancelled"),
        });
      setProgress(null);
    } finally {
      controller.current = null;
      setBusy(false);
    }
  }

  return (
    <div className="devices-tool">
      <label className="devices-field">
        <span>{t("devices.sharedRoot")}</span>
        <Select
          aria-label={t("devices.sharedRoot")}
          value={rootId || undefined}
          placeholder={t("devices.noRoots")}
          disabled={busy}
          onChange={(value) => {
            setRootId(value);
            setPath("");
          }}
          options={device.roots.map((item) => ({
            value: item.id,
            label: item.name,
          }))}
        />
      </label>
      {root && <p className="devices-path">{root.path}</p>}
      <div className="devices-actions">
        <Button
          icon={<ArrowUp size={16} />}
          disabled={!path || busy || !readable}
          onClick={() => setPath(parentPath(path))}
        >
          {t("devices.upDirectory")}
        </Button>
        <Button
          icon={<RefreshCw size={16} />}
          loading={loading}
          disabled={!readable || busy}
          onClick={() => void load()}
        >
          {t("devices.refresh")}
        </Button>
        <Button
          icon={<Upload size={16} />}
          disabled={!writable || busy}
          onClick={() => fileInput.current?.click()}
        >
          {t("devices.upload")}
        </Button>
        <input
          type="file"
          ref={fileInput}
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void upload(file);
          }}
        />
      </div>
      <p className="devices-path">/{path}</p>
      {!readable && (
        <Alert type="info" showIcon message={t("devices.readUnavailable")} />
      )}
      {readable && !loading && entries.length === 0 && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("devices.emptyDirectory")}
        />
      )}
      <div className="devices-file-list">
        {entries.map((entry) => (
          <div className="devices-file" key={entry.path}>
            {entry.is_dir ? <Folder size={17} /> : <File size={17} />}
            <button
              className="devices-file-name"
              disabled={busy}
              onClick={() => {
                if (entry.is_dir) setPath(entry.path);
                else {
                  setSourcePath(entry.path);
                  setTargetPath(entry.name);
                }
              }}
            >
              <span>{entry.name}</span>
              {!entry.is_dir && <small>{formatBytes(entry.size)}</small>}
            </button>
            {!entry.is_dir && (
              <Button
                aria-label={t("devices.downloadNamed", { name: entry.name })}
                icon={<Download size={16} />}
                disabled={busy}
                onClick={() => void prepareDownload(entry)}
              />
            )}
          </div>
        ))}
      </div>
      {progress && (
        <div className="devices-progress">
          <span>
            {t(`devices.${progress.direction}`)} · {device.name} ·{" "}
            {progress.name} · {formatBytes(progress.done)} /{" "}
            {formatBytes(progress.total)}
          </span>
          <Progress
            percent={
              progress.total
                ? Math.min(
                    99,
                    Math.floor((progress.done / progress.total) * 100),
                  )
                : 0
            }
            status="active"
          />
          <Button onClick={() => controller.current?.abort()}>
            {t("devices.cancelLocal")}
          </Button>
        </div>
      )}
      {download && (
        <a
          className="devices-download"
          href={download.url}
          download={download.name}
          target="_blank"
          rel="noopener noreferrer"
        >
          <Download size={16} />
          {t("devices.saveDownload", { name: download.name })}
        </a>
      )}
      {localResult && (
        <Alert
          type={localResult.success ? "success" : "warning"}
          message={localResult.message}
          showIcon
        />
      )}
      <p className="devices-muted">{t("devices.fileHint")}</p>
      <details className="devices-transfer-panel">
        <summary>{t("devices.transferTitle")}</summary>
        <div className="devices-tool devices-transfer-form">
          <label className="devices-field">
            <span>{t("devices.sourceFile")}</span>
            <Input
              value={sourcePath}
              placeholder={t("devices.relativeFile")}
              onChange={(event) => setSourcePath(event.target.value)}
            />
          </label>
          <label className="devices-field">
            <span>{t("devices.targetDevice")}</span>
            <Select
              aria-label={t("devices.targetDevice")}
              value={targetId || undefined}
              onChange={(value) => {
                setTargetId(value);
                setTargetRootId("");
              }}
              options={targets.map((item) => ({
                value: item.device_id,
                label: item.name,
              }))}
            />
          </label>
          <label className="devices-field">
            <span>{t("devices.targetRoot")}</span>
            <Select
              aria-label={t("devices.targetRoot")}
              value={targetRootId || undefined}
              onChange={setTargetRootId}
              options={target?.roots
                .filter((item) => item.write)
                .map((item) => ({ value: item.id, label: item.name }))}
            />
          </label>
          <label className="devices-field">
            <span>{t("devices.targetFile")}</span>
            <Input
              value={targetPath}
              placeholder={t("devices.relativeFile")}
              onChange={(event) => setTargetPath(event.target.value)}
            />
          </label>
          <Button
            loading={transferBusy}
            disabled={
              !readable ||
              !targetRoot ||
              !sourcePath.trim() ||
              !targetPath.trim()
            }
            onClick={async () => {
              if (!targetRoot) return;
              setTransferBusy(true);
              try {
                const operation = await devicesApi.transfer({
                  source_device_id: device.device_id,
                  source_root_id: rootId,
                  source_path: sourcePath,
                  target_device_id: targetId,
                  target_root_id: targetRootId,
                  target_path: targetPath,
                });
                onOperation(operation);
              } catch (error) {
                onError(error);
              } finally {
                setTransferBusy(false);
              }
            }}
          >
            {t("devices.startTransfer")}
          </Button>
          <p className="devices-muted">{t("devices.transferHint")}</p>
        </div>
      </details>
    </div>
  );
}
