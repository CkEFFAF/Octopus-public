import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input, InputNumber } from "antd";
import {
  Code2,
  Download,
  FileText,
  MessageSquare,
  Minus,
  Plus,
  RefreshCw,
  Scan,
} from "lucide-react";
import FileAnnotations from "../../../components/FileAnnotations";
import type { FileAnchor } from "../../../api/modules/annotations";
import Markdown from "../../../components/Markdown";
import CodeEditor from "../../Agent/Workspace/components/CodeEditor";
import { fileSourcesApi } from "../../../api/modules/fileSources";
import {
  collaborationApi,
  downloadCollaborationResource,
  verifiedResourceContent,
  type CollaborationResource,
} from "../../../api/modules/collaboration";
import DocumentPreviewCore from "../../../components/DocumentPreviewCore";
import { isTextFile, decodeUtf8Text } from "../../../utils/textFile";
import { getDocKind } from "../../../utils/docKind";
import { fileTreeIcon } from "../../../utils/fileTreeIcon";
import styles from "./CollaborationPanel.module.less";

/** Immutable resource preview uses opaque identities, never workspace paths. */
export default function ResourcePanelContent({
  agentId,
  threadId,
  resourceId,
}: {
  agentId: string;
  threadId: string;
  resourceId: string;
}) {
  const { t } = useTranslation();
  const [resource, setResource] = useState<CollaborationResource | null>(null);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [textAvailable, setTextAvailable] = useState(false);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [currentId, setCurrentId] = useState(resourceId);
  const [anchor, setAnchor] = useState<FileAnchor>({ kind: "file" });
  const [location, setLocation] = useState<FileAnchor>({ kind: "file" });
  const [annotationsOpen, setAnnotationsOpen] = useState(false);
  const [sourceMode, setSourceMode] = useState(false);
  const [selectionRevision, setSelectionRevision] = useState(0);
  const [imageScale, setImageScale] = useState<number | null>(null);
  const [imageWidth, setImageWidth] = useState(0);
  const [renderedScale, setRenderedScale] = useState(0);
  const image = useRef<HTMLImageElement>(null);
  const host = useRef<HTMLDivElement>(null);
  const media = useRef<HTMLMediaElement | null>(null);
  const regionStart = useRef<[number, number] | null>(null);
  const pageRegion = useRef<{
    element: HTMLElement;
    x: number;
    y: number;
    kind: "page" | "slide";
    page: number;
  } | null>(null);
  useEffect(() => {
    setCurrentId(resourceId);
  }, [resourceId]);
  useEffect(() => {
    setAnchor({ kind: "file" });
    setLocation({ kind: "file" });
    setAnnotationsOpen(false);
    setSourceMode(false);
    setSelectionRevision(0);
    setImageScale(null);
    regionStart.current = null;
    pageRegion.current = null;
  }, [agentId, threadId, currentId]);
  useEffect(() => {
    let active = true;
    let objectUrl = "";
    setLoading(true);
    setError(false);
    setBlob(null);
    setUrl("");
    setText("");
    setTextAvailable(false);
    setResource(null);
    setImageWidth(0);
    setRenderedScale(0);
    void (async () => {
      try {
        const metadata = await collaborationApi.resource(
          agentId,
          threadId,
          currentId,
        );
        if (!["published", "registered"].includes(metadata.publication_state))
          throw new Error("resource_unavailable");
        if (/^(video|audio)\//.test(metadata.media_type)) {
          if (active) {
            setResource(metadata);
            setUrl(
              fileSourcesApi.mediaUrl(agentId, threadId, metadata.resource_id),
            );
          }
          return;
        }
        const bytes = await verifiedResourceContent(
          agentId,
          threadId,
          metadata,
        );
        const textType = isTextFile(metadata.name, metadata.media_type);
        const content = textType
          ? decodeUtf8Text(new Uint8Array(await bytes.arrayBuffer()))
          : "";
        if (!active) return;
        objectUrl = URL.createObjectURL(bytes);
        setResource(metadata);
        setBlob(bytes);
        setText(content);
        setTextAvailable(textType);
        setUrl(objectUrl);
      } catch {
        if (active) setError(true);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [agentId, threadId, currentId, revision]);
  useEffect(() => {
    const node = image.current;
    if (!node) return;
    const update = () => {
      if (node.naturalWidth) {
        setImageWidth(node.naturalWidth);
        setRenderedScale(node.clientWidth / node.naturalWidth);
      }
    };
    const observer = new ResizeObserver(update);
    observer.observe(node);
    node.addEventListener("load", update);
    update();
    return () => {
      observer.disconnect();
      node.removeEventListener("load", update);
    };
  }, [url]);
  const fetchBlob = useCallback(async () => {
    if (!blob) throw new Error("resource_unavailable");
    return blob;
  }, [blob]);
  const download = useCallback(async () => {
    if (!resource) return;
    try {
      await downloadCollaborationResource(agentId, threadId, resource);
    } catch {
      setError(true);
    }
  }, [agentId, threadId, resource]);
  const kind = resource ? getDocKind(resource.name) : null;
  function zoomImage(factor: number) {
    const node = image.current;
    if (!node?.naturalWidth) return;
    setImageScale(
      Math.min(
        4,
        Math.max(0.01, (node.clientWidth / node.naturalWidth) * factor),
      ),
    );
  }
  function selectAnchor(
    value: FileAnchor | ((current: FileAnchor) => FileAnchor),
  ) {
    setAnchor(value);
    setSelectionRevision((value) => value + 1);
    setAnnotationsOpen(true);
  }
  function locate(value: FileAnchor) {
    setLocation(value);
    setAnchor(value);
    if (value.kind === "time" && media.current)
      media.current.currentTime = value.start ?? 0;
    if (value.kind === "text") setSourceMode(true);
    if (value.page)
      host.current
        ?.querySelector(
          `[data-pdf-page="${value.page}"], [data-slide-index="${
            value.page - 1
          }"], [data-document-page="${value.page}"]`,
        )
        ?.scrollIntoView({ block: "center" });
    if (value.kind === "sheet")
      host.current
        ?.querySelector(
          `[data-sheet-name="${CSS.escape(
            value.sheet ?? "",
          )}"] [data-cell="${value.cells?.split(":")[0]}"]`,
        )
        ?.scrollIntoView({ block: "center" });
    if (value.quote && value.kind === "document") {
      const walker = document.createTreeWalker(
        host.current!,
        NodeFilter.SHOW_TEXT,
      );
      let node;
      while ((node = walker.nextNode())) {
        const index = node.textContent?.indexOf(value.quote) ?? -1;
        if (index >= 0) {
          const range = document.createRange();
          range.setStart(node, index);
          range.setEnd(node, index + value.quote.length);
          const selection = window.getSelection();
          selection?.removeAllRanges();
          selection?.addRange(range);
          node.parentElement?.scrollIntoView({ block: "center" });
          break;
        }
      }
    }
  }
  return (
    <div className={styles.annotatedPreview}>
      <div
        className={styles.preview}
        ref={host}
        onPointerDownCapture={(event) => {
          const target = event.target as HTMLElement;
          const element = target.closest<HTMLElement>(
            "[data-pdf-page], [data-slide-index], [data-document-page]",
          );
          if (element) {
            const bounds = element.getBoundingClientRect();
            pageRegion.current = {
              element,
              x: (event.clientX - bounds.left) / bounds.width,
              y: (event.clientY - bounds.top) / bounds.height,
              kind: element.dataset.slideIndex !== undefined ? "slide" : "page",
              page:
                element.dataset.slideIndex !== undefined
                  ? Number(element.dataset.slideIndex) + 1
                  : Number(
                      element.dataset.pdfPage ?? element.dataset.documentPage,
                    ),
            };
          }
        }}
        onPointerUpCapture={(event) => {
          const chosen = pageRegion.current;
          pageRegion.current = null;
          if (!chosen) return;
          const bounds = chosen.element.getBoundingClientRect();
          const x = Math.max(
            0,
            Math.min(1, (event.clientX - bounds.left) / bounds.width),
          );
          const y = Math.max(
            0,
            Math.min(1, (event.clientY - bounds.top) / bounds.height),
          );
          const width = Math.abs(x - chosen.x),
            height = Math.abs(y - chosen.y);
          const selected: FileAnchor = {
            kind: chosen.kind,
            page: chosen.page,
            ...(width > 0.002 && height > 0.002
              ? {
                  rect: [
                    Math.min(x, chosen.x),
                    Math.min(y, chosen.y),
                    width,
                    height,
                  ] as [number, number, number, number],
                }
              : {}),
          };
          if (width > 0.002 && height > 0.002) selectAnchor(selected);
          else setAnchor(selected);
        }}
        onMouseUp={() => {
          const selection = window.getSelection();
          const element = selection?.anchorNode;
          if (
            (element instanceof Element
              ? element
              : element?.parentElement
            )?.closest("[data-preview-chrome]")
          )
            return;
          if (
            selection?.anchorNode &&
            host.current?.contains(selection.anchorNode) &&
            selection.toString().trim()
          ) {
            const node = selection.anchorNode;
            const element = (
              node instanceof Element ? node : node.parentElement
            )?.closest<HTMLElement>(
              "[data-pdf-page], [data-slide-index], [data-document-page]",
            );
            const quote = selection.toString().slice(0, 4000);
            selectAnchor((current) =>
              element
                ? {
                    ...current,
                    kind:
                      element.dataset.slideIndex !== undefined
                        ? "slide"
                        : "page",
                    page:
                      element.dataset.slideIndex !== undefined
                        ? Number(element.dataset.slideIndex) + 1
                        : Number(
                            element.dataset.pdfPage ??
                              element.dataset.documentPage,
                          ),
                    quote,
                  }
                : { kind: "document", quote },
            );
          }
        }}
      >
        <header className={styles.previewHeader} data-preview-chrome>
          <div className={styles.previewIdentity}>
            <span className={styles.previewFileIcon}>
              {resource ? (
                fileTreeIcon(resource.name, 19)
              ) : (
                <FileText size={19} />
              )}
            </span>
            <div>
              <strong title={resource?.name}>
                {resource?.name.split(/[\\/]/).pop() ??
                  t("workspace0034.filePreview")}
              </strong>
              {resource && !error && (
                <details className={styles.resourceProof}>
                  <summary>{t("collaboration.verified")}</summary>
                  <code className={styles.version}>{resource.version}</code>
                </details>
              )}
            </div>
          </div>
          <div className={styles.previewActions}>
            <Button
              size="small"
              type="text"
              icon={<RefreshCw size={15} />}
              aria-label={t("common.refresh")}
              title={t("common.refresh")}
              disabled={loading}
              onClick={() => setRevision((v) => v + 1)}
            />
            {textAvailable &&
              /\.(md|markdown)$/i.test(resource?.name ?? "") && (
                <Button
                  size="small"
                  type="text"
                  icon={<Code2 size={15} />}
                  onClick={() => setSourceMode((v) => !v)}
                  aria-label={t(
                    sourceMode
                      ? "workspace0034.rendered"
                      : "workspace0034.source",
                  )}
                  title={t(
                    sourceMode
                      ? "workspace0034.rendered"
                      : "workspace0034.source",
                  )}
                >
                  <span className={styles.previewActionText}>
                    {t(
                      sourceMode
                        ? "workspace0034.rendered"
                        : "workspace0034.source",
                    )}
                  </span>
                </Button>
              )}
            <Button
              size="small"
              type="text"
              icon={<Download size={15} />}
              aria-label={t("common.download")}
              title={t("common.download")}
              disabled={!resource || loading || error}
              onClick={() => void download()}
            >
              <span className={styles.previewActionText}>
                {t("common.download")}
              </span>
            </Button>
            <Button
              size="small"
              type={annotationsOpen ? "primary" : "default"}
              icon={<MessageSquare size={15} />}
              aria-label={t("workspace0034.annotations")}
              title={t("workspace0034.annotations")}
              onClick={() => {
                setSelectionRevision(0);
                setAnnotationsOpen((value) => !value);
              }}
              aria-expanded={annotationsOpen}
            >
              <span className={styles.previewActionText}>
                {t("workspace0034.annotations")}
              </span>
            </Button>
          </div>
        </header>
        {loading && <p role="status">{t("collaboration.loading")}</p>}
        {error && <p role="alert">{t("collaboration.resourceError")}</p>}
        {resource && !error && (
          <>
            {resource.media_type.startsWith("image/") && (
              <div
                className={`${styles.previewControls} ${styles.imageControls}`}
                data-preview-chrome
              >
                <Button
                  size="small"
                  type="text"
                  aria-label={t("workspace.pdfZoomOut")}
                  icon={<Minus size={14} />}
                  disabled={!imageWidth || renderedScale <= 0.01}
                  onClick={() => zoomImage(1 / 1.25)}
                />
                <span>
                  {imageWidth ? `${Math.round(renderedScale * 100)}%` : "—"}
                </span>
                <Button
                  size="small"
                  type="text"
                  aria-label={t("workspace.pdfZoomIn")}
                  icon={<Plus size={14} />}
                  disabled={!imageWidth || renderedScale >= 4}
                  onClick={() => zoomImage(1.25)}
                />
                <Button
                  size="small"
                  type="text"
                  icon={<Scan size={14} />}
                  disabled={!imageWidth}
                  onClick={() => setImageScale(null)}
                >
                  {t("workspace.pdfFitWidth")}
                </Button>
              </div>
            )}
            {kind && kind !== "pdf" && (
              <div className={styles.previewControls} data-preview-chrome>
                {kind !== "excel" && (
                  <>
                    <span>
                      {t(
                        kind === "pptx"
                          ? "workspace0034.slide"
                          : "workspace0034.page",
                      )}
                    </span>
                    <InputNumber
                      size="small"
                      aria-label={t(
                        kind === "pptx"
                          ? "workspace0034.slide"
                          : "workspace0034.page",
                      )}
                      min={1}
                      value={anchor.page ?? 1}
                      onChange={(page) =>
                        setAnchor({
                          kind: kind === "pptx" ? "slide" : "page",
                          page: page ?? 1,
                        })
                      }
                    />
                  </>
                )}
                {kind === "excel" && (
                  <>
                    <Input
                      size="small"
                      aria-label={t("workspace0034.sheet")}
                      placeholder={t("workspace0034.sheet")}
                      value={anchor.sheet}
                      onChange={(e) =>
                        setAnchor((v) => ({
                          ...v,
                          kind: "sheet",
                          sheet: e.target.value,
                          cells: v.cells ?? "A1",
                        }))
                      }
                    />
                    <Input
                      size="small"
                      aria-label={t("workspace0034.cellRange")}
                      placeholder="A1:B4"
                      value={anchor.cells}
                      onChange={(e) =>
                        setAnchor((v) => ({
                          ...v,
                          kind: "sheet",
                          cells: e.target.value,
                          sheet: v.sheet ?? "Sheet1",
                        }))
                      }
                    />
                  </>
                )}
                <Button size="small" onClick={() => locate(anchor)}>
                  {t("workspace0034.locate")}
                </Button>
              </div>
            )}
            <div className={styles.previewContent}>
              {kind ? (
                <DocumentPreviewCore
                  kind={kind}
                  filename={resource.name}
                  fetchBlob={fetchBlob}
                  onDownload={download}
                  location={anchor}
                  onCellSelect={(sheet, cells) =>
                    selectAnchor({ kind: "sheet", sheet, cells })
                  }
                />
              ) : resource.media_type.startsWith("image/") ? (
                <div
                  className={styles.imageRegion}
                  style={
                    imageScale === null
                      ? undefined
                      : {
                          width: imageWidth * imageScale,
                          maxWidth: "none",
                          alignSelf: "flex-start",
                        }
                  }
                  onPointerDown={(e) => {
                    const bounds = e.currentTarget.getBoundingClientRect();
                    regionStart.current = [
                      (e.clientX - bounds.left) / bounds.width,
                      (e.clientY - bounds.top) / bounds.height,
                    ];
                    e.currentTarget.setPointerCapture(e.pointerId);
                  }}
                  onPointerUp={(e) => {
                    if (!regionStart.current) return;
                    const bounds = e.currentTarget.getBoundingClientRect();
                    const [x, y] = regionStart.current;
                    const right = Math.max(
                      0,
                      Math.min(1, (e.clientX - bounds.left) / bounds.width),
                    );
                    const bottom = Math.max(
                      0,
                      Math.min(1, (e.clientY - bounds.top) / bounds.height),
                    );
                    if (
                      Math.abs(right - x) > 0.001 &&
                      Math.abs(bottom - y) > 0.001
                    )
                      selectAnchor({
                        kind: "image",
                        rect: [
                          Math.min(x, right),
                          Math.min(y, bottom),
                          Math.abs(right - x),
                          Math.abs(bottom - y),
                        ],
                      });
                    regionStart.current = null;
                  }}
                >
                  <img
                    ref={image}
                    src={url}
                    alt={resource.name}
                    draggable={false}
                    style={imageScale === null ? undefined : { width: "100%" }}
                  />
                  {anchor.rect && (
                    <span
                      className={styles.region}
                      style={{
                        left: `${anchor.rect[0] * 100}%`,
                        top: `${anchor.rect[1] * 100}%`,
                        width: `${anchor.rect[2] * 100}%`,
                        height: `${anchor.rect[3] * 100}%`,
                      }}
                    />
                  )}
                </div>
              ) : resource.media_type.startsWith("video/") ? (
                <video
                  ref={(node) => {
                    media.current = node;
                  }}
                  src={url}
                  controls
                  preload="metadata"
                  onError={() => setError(true)}
                />
              ) : resource.media_type.startsWith("audio/") ? (
                <audio
                  ref={(node) => {
                    media.current = node;
                  }}
                  src={url}
                  controls
                  preload="metadata"
                  onError={() => setError(true)}
                />
              ) : textAvailable ? (
                /\.(md|markdown)$/i.test(resource.name) && !sourceMode ? (
                  <Markdown content={text} />
                ) : (
                  <CodeEditor
                    path={resource.name}
                    value={text}
                    readOnly
                    location={location}
                    onSelection={(range) =>
                      selectAnchor({ kind: "text", ...range })
                    }
                    onChange={() => {}}
                  />
                )
              ) : (
                <p>{t("collaboration.noPreview")}</p>
              )}
              {/^(video|audio)\//.test(resource.media_type) && (
                <div
                  className={`${styles.previewControls} ${styles.mediaControls}`}
                  data-preview-chrome
                >
                  <Button
                    size="small"
                    onClick={() =>
                      setAnchor({
                        kind: "time",
                        start: media.current?.currentTime ?? 0,
                        end: media.current?.currentTime ?? 0,
                      })
                    }
                  >
                    {t("workspace0034.markStart")}
                  </Button>
                  <Button
                    size="small"
                    onClick={() => {
                      selectAnchor({
                        kind: "time",
                        start: anchor.start ?? 0,
                        end: Math.max(
                          anchor.start ?? 0,
                          media.current?.currentTime ?? 0,
                        ),
                      });
                    }}
                  >
                    {t("workspace0034.markEnd")}
                  </Button>
                  <span>
                    {anchor.start !== undefined
                      ? `${anchor.start.toFixed(1)}–${(
                          anchor.end ?? anchor.start
                        ).toFixed(1)}s`
                      : t("workspace0034.mediaRangeHint")}
                  </span>
                </div>
              )}
            </div>
          </>
        )}
      </div>
      {resource && !error && annotationsOpen && (
        <div className={styles.annotationPane}>
          <FileAnnotations
            key={currentId}
            agentId={agentId}
            threadId={threadId}
            resource={resource}
            anchor={anchor}
            selectionRevision={selectionRevision}
            onLocate={locate}
            onResult={setCurrentId}
            onClose={() => {
              setSelectionRevision(0);
              setAnnotationsOpen(false);
            }}
          />
        </div>
      )}
    </div>
  );
}
