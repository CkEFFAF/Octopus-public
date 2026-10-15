import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Modal,
  Select,
  Segmented,
  Spin,
  Table,
  Tag,
  Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { FileText, LayoutGrid, List, Radar, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  externalSourcesApi,
  type ExternalSkill as Candidate,
} from "../../../../api/modules/externalSources";
import { devicesApi, type Device } from "../../../../api/modules/devices";
import { executionApi } from "../../../../api/modules/execution";
import { useCurrentUser } from "../../../../hooks/useCurrentUser";
import { CardSkeleton } from "../../../../components/Skeleton";
import { EmptyState } from "../../../../components/EmptyState";
import { useCardTableView } from "../../../../hooks/useCardTableView";
import { showApiError } from "../../../../utils/showApiToast";
import type { SkillSpec } from "../useSkills";
import styles from "../index.module.less";

const SOURCE_NAMES: Record<string, string> = {
  codex: "Codex",
  claude: "Claude Code",
  opencode: "OpenCode",
  opencode_local: "OpenCode",
};
const sourceName = (source: string) => SOURCE_NAMES[source] ?? source;

export default function ExternalSourcesTab({
  agentId,
  installed,
  onImported,
}: {
  agentId: string;
  installed: SkillSpec[];
  onImported: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const currentUser = useCurrentUser();
  const { viewMode, setViewMode, showCardView } = useCardTableView("card");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [source, setSource] = useState("");
  const [devices, setDevices] = useState<Device[]>([]);
  const [sourceNameLabel, setSourceNameLabel] = useState("");
  const [failure, setFailure] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [refreshIndex, setRefreshIndex] = useState(0);
  const epoch = useRef(0);
  const inspection = useRef<AbortController | null>(null);
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    let disposed = false;
    void devicesApi
      .list()
      .then((value) => {
        if (!disposed)
          setDevices(
            value.devices.filter((device) => device.revoked_at === null),
          );
      })
      .catch((error) => {
        if (!disposed) showApiError(error, t("devices.loadFailed"), t);
      });
    return () => {
      disposed = true;
    };
    // The language setting does not change the device inventory.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId]);

  useEffect(() => {
    const generation = ++epoch.current;
    const abort = new AbortController();
    inspection.current?.abort();
    setCandidates([]);
    setSelected(null);
    setInspecting(false);
    setFailure(false);
    if (!source) {
      setLoading(false);
      return () => abort.abort();
    }
    setLoading(true);
    void (async () => {
      try {
        const context =
          source === "__host__"
            ? undefined
            : await executionApi.createContext({
                agent_id: agentId,
                ...(source === "__expert__" ? {} : { device_id: source }),
                work_mode: "ask",
              });
        if (abort.signal.aborted) return;
        const values = await externalSourcesApi.discover(
          agentId,
          context?.context_id,
          abort.signal,
        );
        if (abort.signal.aborted || epoch.current !== generation) return;
        setSourceNameLabel(
          context
            ? context.target_kind === "local"
              ? t("skills.external.host")
              : devices.find((item) => item.device_id === context.device_id)
                  ?.name ??
                context.device_id ??
                t("skills.external.host")
            : t("skills.external.host"),
        );
        setCandidates(values);
      } catch (error) {
        if (!abort.signal.aborted && epoch.current === generation) {
          setFailure(true);
          showApiError(error, t("skills.external.loadFailed"), t);
        }
      } finally {
        if (!abort.signal.aborted && epoch.current === generation)
          setLoading(false);
      }
    })();
    return () => {
      abort.abort();
      inspection.current?.abort();
    };
    // Device list changes must not silently rediscover or change a reviewed snapshot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId, source, refreshIndex]);

  const review = async (candidate: Candidate) => {
    inspection.current?.abort();
    const abort = new AbortController();
    inspection.current = abort;
    const generation = epoch.current;
    setSelected(candidate);
    if (!candidate.needs_inspection) return;
    setInspecting(true);
    try {
      const details = await externalSourcesApi.inspect(
        agentId,
        candidate,
        abort.signal,
      );
      if (!abort.signal.aborted && generation === epoch.current) {
        setSelected({ ...candidate, ...details, needs_inspection: false });
      }
    } catch (error) {
      if (!abort.signal.aborted && generation === epoch.current) {
        setSelected(null);
        showApiError(error, t("skills.external.loadFailed"), t);
      }
    } finally {
      if (!abort.signal.aborted && generation === epoch.current)
        setInspecting(false);
    }
  };

  const approve = async () => {
    if (!selected || selected.needs_inspection || inspecting) return;
    setImporting(true);
    try {
      await externalSourcesApi.import(agentId, selected);
      await onImported();
      setSelected(null);
    } catch (error) {
      showApiError(error, t("skills.external.importFailed"), t);
    } finally {
      setImporting(false);
    }
  };

  const installedSlugs = useMemo(
    () => new Set(installed.map((skill) => skill.slug)),
    [installed],
  );
  const sortedCandidates = useMemo(
    () => candidates.slice().sort((a, b) => a.name.localeCompare(b.name)),
    [candidates],
  );

  const columns: ColumnsType<Candidate> = [
    {
      title: t("skills.nameLabel"),
      dataIndex: "name",
      width: "22%",
      ellipsis: true,
    },
    {
      title: t("skills.skillDescription"),
      dataIndex: "description",
      ellipsis: true,
      render: (description: string) => description || "—",
    },
    {
      title: t("skills.source"),
      dataIndex: "source",
      width: 130,
      render: (source: string) => (
        <Tag className={styles.kindTag}>{sourceName(source)}</Tag>
      ),
    },
    {
      title: t("skills.table.actions"),
      key: "actions",
      width: 110,
      align: "center",
      render: (_value, candidate) => (
        <button
          type="button"
          className={styles.tableActionBtn}
          onClick={(event) => {
            event.stopPropagation();
            void review(candidate);
          }}
        >
          {installedSlugs.has(candidate.slug)
            ? t("skills.external.installed")
            : t("skills.external.review")}
        </button>
      ),
    },
  ];

  const content =
    loading && candidates.length === 0 ? (
      <CardSkeleton count={6} />
    ) : !source ? (
      <EmptyState
        title={t("skills.external.chooseSource")}
        description={t("skills.external.deviceHint")}
      />
    ) : failure ? (
      <Alert type="error" showIcon message={t("skills.external.loadFailed")} />
    ) : sortedCandidates.length === 0 ? (
      <EmptyState
        title={t("skills.external.empty")}
        description={sourceNameLabel}
      />
    ) : showCardView ? (
      <div className={styles.skillsGrid}>
        {sortedCandidates.map((candidate) => {
          const alreadyInstalled = installedSlugs.has(candidate.slug);
          return (
            <div
              key={candidate.source + ":" + candidate.slug}
              className={styles.skillCard}
              role="button"
              tabIndex={0}
              onClick={() => void review(candidate)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void review(candidate);
              }}
            >
              <div className={styles.cardBody}>
                <div className={styles.cardHeader}>
                  <div
                    className={styles.iconWrapper}
                    style={{
                      color: "var(--fn-color-brand)",
                      background: "var(--fn-color-brand-bg)",
                    }}
                  >
                    <Radar size={22} />
                  </div>
                  <div className={styles.cardMeta}>
                    <div className={styles.cardTitle} title={candidate.name}>
                      {candidate.name}
                    </div>
                    <div className={styles.cardBadges}>
                      <span className={styles.builtinBadge}>
                        {sourceName(candidate.source)}
                      </span>
                      {alreadyInstalled ? (
                        <span className={styles.enabledBadge}>
                          ✓ {t("skills.external.installed")}
                        </span>
                      ) : null}
                    </div>
                  </div>
                </div>
                <div
                  className={styles.cardDesc}
                  title={candidate.description || undefined}
                >
                  {candidate.description || t("skills.noDescription")}
                </div>
                <div className={styles.cardFooter}>
                  <span className={styles.detailBtn}>
                    <FileText size={14} />
                    {t("skills.external.files", {
                      count: candidate.file_count,
                    })}
                  </span>
                  <button
                    type="button"
                    className={[
                      styles.applyBtn,
                      alreadyInstalled
                        ? styles.appliedBtn
                        : styles.applyActiveBtn,
                    ].join(" ")}
                    onClick={(event) => {
                      event.stopPropagation();
                      void review(candidate);
                    }}
                  >
                    {alreadyInstalled
                      ? t("skills.external.installed")
                      : t("skills.external.review")}
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    ) : (
      <Table<Candidate>
        className={styles.skillsTable}
        rowKey={(candidate) => candidate.source + ":" + candidate.slug}
        columns={columns}
        dataSource={sortedCandidates}
        pagination={false}
        size="middle"
        scroll={{ x: 720 }}
        onRow={(candidate) => ({
          onClick: () => void review(candidate),
          style: { cursor: "pointer" },
        })}
      />
    );

  return (
    <>
      <p className={styles.packageMountHint}>
        {t("skills.external.deviceHint")}
      </p>
      <div className={styles.gridToolbar}>
        <div>
          <Select
            aria-label={t("skills.external.chooseSource")}
            placeholder={t("skills.external.chooseSource")}
            value={source || undefined}
            style={{ minWidth: 240, maxWidth: "100%", marginRight: 12 }}
            disabled={importing}
            onChange={(value) => {
              ++epoch.current;
              inspection.current?.abort();
              setSource(value);
              setSelected(null);
            }}
            options={[
              { value: "__expert__", label: t("skills.external.expertDevice") },
              ...devices.map((device) => ({
                value: device.device_id,
                label: `${device.name} · ${t(
                  device.online ? "devices.online" : "devices.offline",
                )}`,
                disabled:
                  !device.online ||
                  device.trust_mode !== "owner" ||
                  device.runtime?.capability_protocol_version !== 1,
              })),
              ...(currentUser?.role === "admin"
                ? [{ value: "__host__", label: t("skills.external.host") }]
                : []),
            ]}
          />
          <span className={styles.gridCount}>
            {t("skills.totalCount", { count: sortedCandidates.length })}
          </span>
        </div>
        <div className={styles.gridToolbarRight}>
          <Segmented
            size="small"
            value={viewMode}
            onChange={(value) =>
              setViewMode(value === "table" ? "table" : "card")
            }
            options={[
              {
                value: "card",
                label: (
                  <span className={styles.viewModeLabel}>
                    <LayoutGrid size={14} />
                    {t("experts.viewCard")}
                  </span>
                ),
              },
              {
                value: "table",
                label: (
                  <span className={styles.viewModeLabel}>
                    <List size={14} />
                    {t("experts.viewTable")}
                  </span>
                ),
              },
            ]}
          />
          <Tooltip title={t("skills.external.refresh")}>
            <button
              type="button"
              className={styles.toolbarIconBtn}
              onClick={() => setRefreshIndex((value) => value + 1)}
              disabled={loading || importing || !source}
              aria-label={t("skills.external.refresh")}
            >
              <RefreshCw
                size={14}
                className={loading ? styles.spinning : undefined}
              />
            </button>
          </Tooltip>
        </div>
      </div>
      <div className={styles.skillsListArea}>{content}</div>
      <Modal
        open={selected !== null}
        title={selected?.name}
        onCancel={() => {
          if (!importing) {
            inspection.current?.abort();
            setSelected(null);
            setInspecting(false);
          }
        }}
        onOk={() => void approve()}
        okText={t("skills.external.approve")}
        okButtonProps={{
          disabled:
            inspecting ||
            !!selected?.needs_inspection ||
            (!!selected && installedSlugs.has(selected.slug)),
        }}
        confirmLoading={importing}
        destroyOnClose
      >
        <p>
          {sourceNameLabel}
          {selected?.path ? ` · ${selected.path}` : ""}
        </p>
        <p className={styles.packageDetailHint}>
          {t("skills.external.reviewHint", {
            source: sourceName(selected?.source ?? ""),
          })}
        </p>
        {inspecting ? (
          <Spin />
        ) : (
          <>
            <div className={styles.externalFileList}>
              {selected?.files.map((file) => <Tag key={file}>{file}</Tag>)}
            </div>
            <pre className={styles.externalManifest}>{selected?.manifest}</pre>
          </>
        )}
      </Modal>
    </>
  );
}
