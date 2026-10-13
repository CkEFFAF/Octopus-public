import { useEffect, useMemo, useState } from "react";
import { Modal, Segmented, Table, Tag, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import { FileText, LayoutGrid, List, Radar, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { request } from "../../../../api/request";
import { CardSkeleton } from "../../../../components/Skeleton";
import { EmptyState } from "../../../../components/EmptyState";
import { useCardTableView } from "../../../../hooks/useCardTableView";
import { showApiError } from "../../../../utils/showApiToast";
import type { SkillSpec } from "../useSkills";
import styles from "../index.module.less";

type Candidate = {
  source: string;
  slug: string;
  name: string;
  description: string;
  digest: string;
  manifest: string;
  files: string[];
  file_count: number;
};

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
  const { viewMode, setViewMode, showCardView } = useCardTableView("card");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [importing, setImporting] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      setCandidates(
        await request<Candidate[]>(
          "/agents/" +
            encodeURIComponent(agentId) +
            "/skills/external/discover",
          { cache: "no-store" },
        ),
      );
    } catch (error) {
      showApiError(error, t("skills.external.loadFailed"), t);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    // Refresh whenever the target expert changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId]);

  const approve = async () => {
    if (!selected) return;
    setImporting(true);
    try {
      await request(
        "/agents/" + encodeURIComponent(agentId) + "/skills/external/import",
        {
          method: "POST",
          body: JSON.stringify({
            source: selected.source,
            slug: selected.slug,
            digest: selected.digest,
          }),
        },
      );
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
            setSelected(candidate);
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
    ) : sortedCandidates.length === 0 ? (
      <EmptyState
        title={t("skills.external.empty")}
        description={t("skills.external.serverOnly")}
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
              onClick={() => setSelected(candidate)}
              onKeyDown={(event) => {
                if (event.key === "Enter") setSelected(candidate);
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
                      setSelected(candidate);
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
          onClick: () => setSelected(candidate),
          style: { cursor: "pointer" },
        })}
      />
    );

  return (
    <>
      <p className={styles.packageMountHint}>
        {t("skills.external.serverOnly")}
      </p>
      <div className={styles.gridToolbar}>
        <span className={styles.gridCount}>
          {t("skills.totalCount", { count: sortedCandidates.length })}
        </span>
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
              onClick={() => void refresh()}
              disabled={loading}
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
        onCancel={() => setSelected(null)}
        onOk={() => void approve()}
        okText={t("skills.external.approve")}
        okButtonProps={{
          disabled: !!selected && installedSlugs.has(selected.slug),
        }}
        confirmLoading={importing}
        destroyOnClose
      >
        <p className={styles.packageDetailHint}>
          {t("skills.external.reviewHint", {
            source: sourceName(selected?.source ?? ""),
          })}
        </p>
        <div className={styles.externalFileList}>
          {selected?.files.map((file) => <Tag key={file}>{file}</Tag>)}
        </div>
        <pre className={styles.externalManifest}>{selected?.manifest}</pre>
      </Modal>
    </>
  );
}
