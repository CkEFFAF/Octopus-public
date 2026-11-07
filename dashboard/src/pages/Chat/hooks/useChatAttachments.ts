import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { ChangeEvent, ClipboardEvent, DragEvent } from "react";
import { useTranslation } from "react-i18next";
import { uploadFile } from "../../../api/modules/upload";
import { agentAttachmentAccessUrl } from "../../../utils/toolMediaBlocks";
import type { ChatAttachment } from "./useChat";
import { message as antMessage } from "@/utils/antdMessage";
import { apiErrorMessage } from "../../../utils/apiError";

import { inferAttachmentKind } from "../utils/chatAttachments";
import { useServerUploadLimit } from "../../../hooks/useServerUploadLimit";

export interface AttachmentUpload {
  id: string;
  filename: string;
  percent: number;
  status: "uploading" | "failed";
  error?: string;
}

export function useChatAttachments(
  agentId: string | null | undefined,
  threadId?: string | null,
) {
  const { t } = useTranslation();
  const { maxUploadBytes, maxUploadMb } = useServerUploadLimit();
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [uploads, setUploads] = useState<AttachmentUpload[]>([]);
  const jobs = useRef(
    new Map<string, { file: File; controller: AbortController }>(),
  );
  const generation = useRef(0);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const reset = useCallback(() => {
    generation.current += 1;
    jobs.current.forEach(({ controller }) => controller.abort());
    jobs.current.clear();
    setUploads([]);
    setAttachments([]);
  }, []);

  useLayoutEffect(() => {
    reset();
    setDragOver(false);
    const pending = jobs.current;
    return () => {
      generation.current += 1;
      pending.forEach(({ controller }) => controller.abort());
      pending.clear();
    };
  }, [agentId, threadId, reset]);

  const uploadOne = useCallback(
    async (id: string, file: File) => {
      if (!agentId) return;
      const epoch = generation.current;
      const controller = new AbortController();
      jobs.current.set(id, { file, controller });
      setUploads((prev) => [
        ...prev.filter((item) => item.id !== id),
        {
          id,
          filename: file.name,
          percent: 0,
          status: "uploading",
        },
      ]);
      const current = () =>
        generation.current === epoch &&
        jobs.current.get(id)?.controller === controller &&
        !controller.signal.aborted;
      try {
        const res = await uploadFile(agentId, file, {
          signal: controller.signal,
          onProgress: (percent) => {
            if (current())
              setUploads((prev) =>
                prev.map((item) =>
                  item.id === id
                    ? { ...item, percent: Math.max(0, Math.min(100, percent)) }
                    : item,
                ),
              );
          },
        });
        if (!current()) return;
        const workspacePath = res.path || res.workspace_path;
        const attachment: ChatAttachment = {
          size: file.size,
          url:
            res.access_url ||
            res.url ||
            (workspacePath
              ? agentAttachmentAccessUrl(agentId, workspacePath, res.media_type)
              : ""),
          filename: res.filename,
          mediaType: res.media_type,
          workspacePath,
          resourceId: res.resource_id,
          version: res.version,
          kind: inferAttachmentKind(file, res.media_type),
        };
        setAttachments((prev) => [...prev, attachment]);
        setUploads((prev) => prev.filter((item) => item.id !== id));
        jobs.current.delete(id);
      } catch (err) {
        if (!current()) return;
        setUploads((prev) =>
          prev.map((item) =>
            item.id === id
              ? {
                  ...item,
                  status: "failed",
                  error: apiErrorMessage(
                    err,
                    t("upload.failed", "Upload failed"),
                    t,
                  ),
                }
              : item,
          ),
        );
      }
    },
    [agentId, t],
  );

  const cancelUpload = useCallback((id: string) => {
    jobs.current.get(id)?.controller.abort();
    jobs.current.delete(id);
    setUploads((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const retryUpload = useCallback(
    (id: string) => {
      const job = jobs.current.get(id);
      if (!job) return;
      job.controller.abort();
      void uploadOne(id, job.file);
    },
    [uploadOne],
  );

  const processFiles = useCallback(
    async (files: FileList | File[]) => {
      const fileArr = Array.from(files).filter((f) => {
        if (f.size > maxUploadBytes) {
          antMessage.error(
            t("upload.tooLarge", "File too large (max {{maxMb}}MB): {{name}}", {
              name: f.name,
              maxMb: maxUploadMb,
            }),
          );
          return false;
        }
        return true;
      });

      if (fileArr.length === 0) return;

      if (!agentId) {
        antMessage.error(t("upload.failed", "Upload failed"));
        return;
      }

      await Promise.all(
        fileArr.map((file) => uploadOne(crypto.randomUUID(), file)),
      );
    },
    [agentId, maxUploadBytes, maxUploadMb, t, uploadOne],
  );

  const handleFileSelect = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        void processFiles(e.target.files);
      }
      e.target.value = "";
    },
    [processFiles],
  );

  const removeAttachment = useCallback((index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const clearAttachments = reset;
  const consumeAttachments = useCallback((submitted: ChatAttachment[]) => {
    const sent = new Set(submitted);
    setAttachments((current) => current.filter((item) => !sent.has(item)));
  }, []);

  const restoreAttachments = useCallback(
    (next: ChatAttachment[]) => {
      reset();
      setAttachments(next.map((a) => ({ ...a })));
    },
    [reset],
  );

  const handlePaste = useCallback(
    (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      const pastedFiles: File[] = [];
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.kind === "file") {
          const file = item.getAsFile();
          if (file) pastedFiles.push(file);
        }
      }
      if (pastedFiles.length > 0) {
        e.preventDefault();
        void processFiles(pastedFiles);
      }
    },
    [processFiles],
  );

  const handleDragEnter = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  }, []);

  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragOver(false);
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        void processFiles(e.dataTransfer.files);
      }
    },
    [processFiles],
  );

  return {
    attachments,
    uploading: uploads.some((item) => item.status === "uploading"),
    uploads,
    cancelUpload,
    retryUpload,
    dragOver,
    fileInputRef,
    processFiles,
    handleFileSelect,
    handleFileChange,
    removeAttachment,
    clearAttachments,
    consumeAttachments,
    restoreAttachments,
    handlePaste,
    handleDragEnter,
    handleDragLeave,
    handleDragOver,
    handleDrop,
  };
}
