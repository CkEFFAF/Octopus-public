import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Alert,
  Button,
  Checkbox,
  Drawer,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Spin,
} from "antd";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Pencil,
  Pin,
  Plus,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  pinnedFilesApi,
  type PinnedFile,
  type PinnedFiles,
} from "../api/modules/pinnedFiles";
import { devicesApi, type Device } from "../api/modules/devices";
import { executionApi, type ExecutionContext } from "../api/modules/execution";
import { useCurrentUser } from "../hooks/useCurrentUser";
import { parseApiError } from "../utils/apiError";
import styles from "./PinnedFilesPanel.module.less";

const FilePanelContent = lazy(
  () => import("../pages/Chat/components/FilePanelContent"),
);
const ExecutionWorkbench = lazy(
  () => import("../pages/Chat/components/ExecutionWorkbench"),
);
const changedEvent = "octop:pinned-files-changed";

interface PinForm {
  title: string;
  scope: "expert" | "project";
  path: string;
  target?: string;
  working_dir?: string;
}

/** Expert-scoped bookmarks persist across chat sessions and retain their source. */
export default function PinnedFilesPanel({
  agentId,
  threadId,
  defaultCollapsed = false,
}: {
  agentId: string;
  threadId?: string | null;
  defaultCollapsed?: boolean;
}) {
  const { t } = useTranslation();
  const user = useCurrentUser();
  const [data, setData] = useState<PinnedFiles>({ revision: 0, files: [] });
  const [hidden, setHidden] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const listId = useId();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [removeConfirmOpen, setRemoveConfirmOpen] = useState(false);
  const [editing, setEditing] = useState<PinnedFile | "new" | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [viewing, setViewing] = useState<{
    pin: PinnedFile;
    context?: ExecutionContext;
  } | null>(null);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState("");
  const [actions, setActions] = useState<ReactNode>(null);
  const [form] = Form.useForm<PinForm>();
  const scope = Form.useWatch("scope", form);
  const epoch = useRef(0);
  const loadSequence = useRef(0);
  const viewSequence = useRef(0);
  const savingRef = useRef(false);

  const load = useCallback(async () => {
    if (!agentId) return;
    const stamp = ++loadSequence.current;
    setLoading(true);
    try {
      const response = await pinnedFilesApi.get(agentId);
      if (stamp !== loadSequence.current) return;
      setData(response);
      setHidden(false);
      setLoaded(true);
      setError("");
    } catch (err) {
      if (stamp !== loadSequence.current) return;
      if (parseApiError(err)?.code === "FORBIDDEN") setHidden(true);
      else setError(t("pinnedFiles.loadFailed"));
    } finally {
      if (stamp === loadSequence.current) setLoading(false);
    }
  }, [agentId, t]);

  useEffect(() => {
    epoch.current += 1;
    setData({ revision: 0, files: [] });
    setHidden(false);
    setLoaded(false);
    setSelecting(false);
    setSelectedIds(new Set());
    setRemoveConfirmOpen(false);
    setError("");
    setEditing(null);
    setViewing(null);
    setActions(null);
    setSaving(false);
    savingRef.current = false;
    void load();
    const changed = (event: Event) => {
      if ((event as CustomEvent<string>).detail === agentId) void load();
    };
    window.addEventListener(changedEvent, changed);
    return () => {
      epoch.current += 1;
      loadSequence.current += 1;
      viewSequence.current += 1;
      window.removeEventListener(changedEvent, changed);
    };
  }, [agentId, load]);

  useEffect(() => {
    if (editing === null) return;
    let cancelled = false;
    void devicesApi
      .list()
      .then(({ devices: rows }) => {
        if (!cancelled) setDevices(rows);
      })
      .catch(() => {
        if (!cancelled) setDevices([]);
      });
    return () => {
      cancelled = true;
    };
  }, [editing]);

  useEffect(() => {
    viewSequence.current += 1;
    setViewing(null);
    setOpening(false);
    setActions(null);
  }, [threadId]);

  const persist = async (files: PinnedFile[]) => {
    if (savingRef.current || loading || !loaded) return false;
    const stamp = epoch.current;
    savingRef.current = true;
    setSaving(true);
    try {
      const saved = await pinnedFilesApi.save(agentId, {
        revision: data.revision,
        files,
      });
      if (stamp !== epoch.current) return false;
      loadSequence.current += 1;
      setData(saved);
      setError("");
      window.dispatchEvent(new CustomEvent(changedEvent, { detail: agentId }));
      return true;
    } catch (err) {
      if (stamp !== epoch.current) return false;
      const conflict =
        parseApiError(err)?.details?.reason === "pinned_files_conflict";
      // Refresh the list while keeping the user's form draft available.
      if (conflict) {
        await load();
        if (stamp !== epoch.current) return false;
      }
      setError(t(conflict ? "pinnedFiles.conflict" : "pinnedFiles.saveFailed"));
      return false;
    } finally {
      if (stamp === epoch.current) {
        savingRef.current = false;
        setSaving(false);
      }
    }
  };

  const selectedFiles = data.files.filter((pin) => selectedIds.has(pin.id));
  const blocked = !loaded || loading || saving;
  const toggleSelected = (id: string) => {
    if (blocked || savingRef.current) return;
    setSelectedIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const removeSelected = async () => {
    if (blocked || savingRef.current || !selectedFiles.length) return;
    if (await persist(data.files.filter((pin) => !selectedIds.has(pin.id)))) {
      setSelecting(false);
      setSelectedIds(new Set());
      setRemoveConfirmOpen(false);
    }
  };

  const edit = (pin?: PinnedFile) => {
    form.resetFields();
    form.setFieldsValue(
      pin
        ? {
            title: pin.title,
            scope: pin.scope,
            path: pin.path,
            target:
              pin.target_kind === "local"
                ? "@local"
                : pin.device_id ?? undefined,
            working_dir: pin.working_dir ?? undefined,
          }
        : { title: "", scope: "expert", path: "" },
    );
    setEditing(pin ?? "new");
  };

  const save = async () => {
    const values = await form.validateFields().catch(() => null);
    if (!values || !editing) return;
    if (
      editing !== "new" &&
      !data.files.some((item) => item.id === editing.id)
    ) {
      setError(t("pinnedFiles.conflict"));
      return;
    }
    const pin: PinnedFile = {
      id: editing === "new" ? crypto.randomUUID() : editing.id,
      title: values.title.trim(),
      scope: values.scope,
      path: values.path.trim(),
      ...(values.scope === "project"
        ? {
            target_kind: values.target === "@local" ? "local" : "device",
            device_id: values.target === "@local" ? null : values.target,
            working_dir: values.working_dir?.trim(),
          }
        : {}),
    };
    const next =
      editing === "new"
        ? [...data.files, pin]
        : data.files.map((item) => (item.id === pin.id ? pin : item));
    if (await persist(next)) setEditing(null);
  };

  const open = async (pin: PinnedFile) => {
    const stamp = ++viewSequence.current;
    setViewing({ pin });
    setActions(null);
    setOpenError("");
    setOpening(pin.scope === "project");
    if (pin.scope === "expert") return;
    try {
      const context = await executionApi.createContext({
        agent_id: agentId,
        ...(threadId && !threadId.startsWith("__")
          ? { thread_id: threadId }
          : {}),
        target_kind: pin.target_kind ?? undefined,
        device_id: pin.device_id ?? undefined,
        working_dir: pin.working_dir ?? undefined,
        work_mode: "agentic",
      });
      if (stamp === viewSequence.current) setViewing({ pin, context });
    } catch {
      if (stamp === viewSequence.current)
        setOpenError(t("pinnedFiles.openFailed"));
    } finally {
      if (stamp === viewSequence.current) setOpening(false);
    }
  };

  if (hidden || !agentId) return null;
  const targetOptions = devices.map((device) => ({
    value: device.device_id,
    label: device.name,
  }));
  if (user?.role === "admin")
    targetOptions.unshift({ value: "@local", label: t("pinnedFiles.local") });
  if (
    editing &&
    editing !== "new" &&
    editing.device_id &&
    !targetOptions.some((item) => item.value === editing.device_id)
  ) {
    targetOptions.push({ value: editing.device_id, label: editing.device_id });
  }

  return (
    <section className={styles.panel} aria-label={t("pinnedFiles.title")}>
      <div className={styles.heading}>
        <button
          type="button"
          className={styles.toggle}
          aria-expanded={!collapsed}
          aria-controls={listId}
          onClick={() => setCollapsed((value) => !value)}
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
          <Pin size={14} />
          {t("pinnedFiles.title")}
          {loaded && <span className={styles.count}>{data.files.length}</span>}
        </button>
        <div className={styles.headingActions}>
          {selecting ? (
            <>
              <Button
                size="small"
                type="text"
                disabled={blocked}
                onClick={() => {
                  setSelecting(false);
                  setSelectedIds(new Set());
                  setRemoveConfirmOpen(false);
                }}
              >
                {t("pinnedFiles.cancelSelection")}
              </Button>
              <Button
                size="small"
                danger
                type="primary"
                disabled={blocked || !selectedFiles.length}
                loading={saving}
                onClick={() => setRemoveConfirmOpen(true)}
              >
                {t("pinnedFiles.deleteSelected", {
                  count: selectedFiles.length,
                })}
              </Button>
            </>
          ) : (
            <>
              <Button
                size="small"
                type="text"
                disabled={blocked || data.files.length >= 32}
                onClick={() => edit()}
                icon={<Plus size={14} />}
              >
                {t("pinnedFiles.add")}
              </Button>
              <Button
                size="small"
                type="text"
                disabled={blocked || editing !== null || !data.files.length}
                icon={<Trash2 size={14} />}
                onClick={() => {
                  viewSequence.current += 1;
                  setViewing(null);
                  setActions(null);
                  setOpening(false);
                  setSelectedIds(new Set());
                  setSelecting(true);
                  setCollapsed(false);
                }}
              >
                {t("pinnedFiles.delete")}
              </Button>
            </>
          )}
        </div>
      </div>
      {selecting && !collapsed && (
        <div className={styles.selectionBar}>
          <Checkbox
            disabled={blocked}
            checked={
              !!data.files.length && selectedFiles.length === data.files.length
            }
            indeterminate={
              !!selectedFiles.length && selectedFiles.length < data.files.length
            }
            onChange={(event) => {
              if (blocked || savingRef.current) return;
              setSelectedIds(
                event.target.checked
                  ? new Set(data.files.map((pin) => pin.id))
                  : new Set(),
              );
            }}
          >
            {t("pinnedFiles.selectAll")}
          </Checkbox>
          <span>
            {t("pinnedFiles.selectedCount", { count: selectedFiles.length })}
          </span>
        </div>
      )}
      {error && (
        <Alert
          type="error"
          message={error}
          action={
            <Button
              size="small"
              disabled={loading || saving}
              onClick={() => void load()}
            >
              {t("pinnedFiles.refresh")}
            </Button>
          }
        />
      )}
      {!collapsed && !loaded && !error ? <Spin size="small" /> : null}
      {!collapsed && loaded && data.files.length === 0 && (
        <p className={styles.hint}>{t("pinnedFiles.empty")}</p>
      )}
      <div id={listId} className={styles.list} hidden={collapsed}>
        {data.files.map((pin) => (
          <div
            className={`${styles.row} ${
              selecting && selectedIds.has(pin.id) ? styles.selected : ""
            }`}
            key={pin.id}
          >
            {selecting && (
              <Checkbox
                aria-label={t("pinnedFiles.selectFile", { title: pin.title })}
                checked={selectedIds.has(pin.id)}
                disabled={blocked}
                onChange={() => toggleSelected(pin.id)}
              />
            )}
            <button
              className={styles.file}
              type="button"
              disabled={blocked}
              aria-pressed={selecting ? selectedIds.has(pin.id) : undefined}
              onClick={() =>
                selecting ? toggleSelected(pin.id) : void open(pin)
              }
            >
              <FileText
                size={18}
                className={styles.fileIcon}
                aria-hidden="true"
              />
              <span className={styles.fileCopy}>
                <strong title={pin.title}>{pin.title}</strong>
              </span>
            </button>
            {!selecting && (
              <Button
                size="small"
                type="text"
                className={styles.edit}
                aria-label={t("pinnedFiles.edit", { title: pin.title })}
                icon={<Pencil size={14} />}
                disabled={blocked}
                onClick={() => edit(pin)}
              />
            )}
          </div>
        ))}
      </div>
      <Modal
        open={removeConfirmOpen}
        title={t("pinnedFiles.deleteConfirmTitle", {
          count: selectedFiles.length,
        })}
        okText={t("pinnedFiles.deleteSelected", {
          count: selectedFiles.length,
        })}
        cancelText={t("pinnedFiles.cancelSelection")}
        okButtonProps={{
          danger: true,
          disabled: blocked || !selectedFiles.length,
        }}
        cancelButtonProps={{ disabled: saving }}
        confirmLoading={saving}
        closable={!saving}
        maskClosable={!saving}
        keyboard={!saving}
        onOk={() => void removeSelected()}
        onCancel={() => !saving && setRemoveConfirmOpen(false)}
      >
        <p>{t("pinnedFiles.removeConfirm")}</p>
        <ul className={styles.removalList}>
          {selectedFiles.map((pin) => (
            <li key={pin.id}>{pin.title}</li>
          ))}
        </ul>
        {error && <Alert type="error" message={error} />}
      </Modal>
      <Modal
        open={editing !== null}
        title={t("pinnedFiles.manageTitle")}
        onCancel={() => !saving && setEditing(null)}
        onOk={() => void save()}
        okButtonProps={{ disabled: blocked }}
        confirmLoading={saving}
        forceRender
      >
        <Form
          form={form}
          layout="vertical"
          preserve={false}
          disabled={loading || saving}
        >
          <Form.Item
            name="title"
            label={t("pinnedFiles.label")}
            rules={[{ required: true, whitespace: true }]}
          >
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item
            name="scope"
            label={t("pinnedFiles.source")}
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { value: "expert", label: t("pinnedFiles.expert") },
                { value: "project", label: t("pinnedFiles.project") },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="path"
            label={t("pinnedFiles.path")}
            extra={
              scope === "expert"
                ? t("pinnedFiles.expertPathHint")
                : t("pinnedFiles.projectPathHint")
            }
            rules={[{ required: true, whitespace: true }]}
          >
            <Input maxLength={4096} />
          </Form.Item>
          {scope === "project" && (
            <>
              <Form.Item
                name="target"
                label={t("pinnedFiles.target")}
                rules={[{ required: true }]}
              >
                <Select
                  showSearch
                  optionFilterProp="label"
                  options={targetOptions}
                />
              </Form.Item>
              <Form.Item
                name="working_dir"
                label={t("pinnedFiles.workingDir")}
                rules={[{ required: true, whitespace: true }]}
              >
                <Input maxLength={4096} />
              </Form.Item>
            </>
          )}
        </Form>
        {error && <Alert type="error" message={error} />}
      </Modal>
      <Drawer
        open={viewing !== null}
        title={viewing?.pin.title}
        width="min(960px, 100vw)"
        onClose={() => {
          viewSequence.current += 1;
          setViewing(null);
          setActions(null);
        }}
        destroyOnHidden
        styles={{
          body: { display: "flex", flexDirection: "column", padding: 16 },
        }}
      >
        {viewing && (
          <>
            <p className={styles.hint}>{viewing.pin.path}</p>
            <Space className={styles.actions}>{actions}</Space>
            {openError ? (
              <Alert type="error" message={openError} />
            ) : opening ? (
              <Spin />
            ) : (
              <Suspense fallback={<Spin />}>
                {viewing.pin.scope === "expert" ? (
                  <FilePanelContent
                    key={`${agentId}:${viewing.pin.id}`}
                    agentId={agentId}
                    filePath={viewing.pin.path}
                    onActionsChange={setActions}
                  />
                ) : viewing.context ? (
                  <ExecutionWorkbench
                    key={viewing.context.context_id}
                    context={viewing.context}
                    surface="workspace"
                    initialFilePath={viewing.pin.path}
                    visible
                    agentId={agentId}
                    threadId={threadId}
                  />
                ) : null}
              </Suspense>
            )}
          </>
        )}
      </Drawer>
    </section>
  );
}
