import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Popover, Spin, Drawer } from "antd";
import {
  octopThreadsApi,
  type ContextUsageBreakdown,
  type ContextUsageSegmentKey,
} from "../../../api/modules/octopThreads";
import { isPendingThread } from "../hooks/useSessions";
import { contextUsedPercent } from "../hooks/useChatContextWindow";
import {
  isCapacityResolved,
  occupancyPercent,
} from "../contextInsights/capacity";
import styles from "../index.module.less";

const DEFAULT_MAX = 128_000;
const BREAKDOWN_CACHE_TTL_MS = 30_000;

const SEGMENT_COLORS: Record<ContextUsageSegmentKey, string> = {
  system_prompt: "#9ca3af",
  tool_definitions: "#c4b5fd",
  rules: "#86efac",
  skills: "#fbbf24",
  mcp: "#e879f9",
  subagent_definitions: "#3b82f6",
  conversation: "#22d3ee",
};

function formatTokenK(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`;
  return String(n);
}

interface ContextWindowRingProps {
  usedTokens: number | null;
  maxTokens: number;
  agentId?: string | null;
  threadId?: string | null;
  selectedConnectors?: string[];
  isMobile?: boolean;
  onInspect?: () => void;
}

export default function ContextWindowRing({
  usedTokens,
  maxTokens,
  agentId,
  threadId,
  selectedConnectors = [],
  isMobile = false,
  onInspect,
}: ContextWindowRingProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [breakdown, setBreakdown] = useState<ContextUsageBreakdown | null>(
    null,
  );
  const cacheRef = useRef<{
    key: string;
    at: number;
    data: ContextUsageBreakdown;
  } | null>(null);

  const max = maxTokens > 0 ? maxTokens : DEFAULT_MAX;
  const hintUsed = usedTokens ?? 0;

  const cacheKey = useMemo(
    () =>
      [
        agentId ?? "",
        threadId ?? "",
        String(max),
        selectedConnectors.join(","),
      ].join("|"),
    [agentId, threadId, max, selectedConnectors],
  );

  const loadBreakdown = useCallback(
    async (opts?: { silent?: boolean; force?: boolean }) => {
      if (!agentId || !threadId || isPendingThread(threadId)) return;
      const cached = cacheRef.current;
      if (
        !opts?.force &&
        cached &&
        cached.key === cacheKey &&
        Date.now() - cached.at < BREAKDOWN_CACHE_TTL_MS
      ) {
        setBreakdown(cached.data);
        return;
      }
      if (!opts?.silent) setLoading(true);
      try {
        // DEC-T14: prefer Insights-backed context-usage (no preview params)
        // so capacity_source is real. Preview overrides fake capacity.
        const data = await octopThreadsApi.contextUsage(agentId, threadId, {
          mcpServers:
            selectedConnectors.length > 0 ? selectedConnectors : undefined,
        });
        if (data.used_tokens > 0) {
          cacheRef.current = { key: cacheKey, at: Date.now(), data };
          setBreakdown(data);
        } else {
          // Empty harness snapshot (old threads) must not pin the ring at 0%.
          cacheRef.current = null;
          setBreakdown(null);
        }
      } catch {
        if (!opts?.silent) setBreakdown(null);
      } finally {
        if (!opts?.silent) setLoading(false);
      }
    },
    [agentId, threadId, max, selectedConnectors, cacheKey],
  );

  // Reset detail cache on thread/filter changes.
  useEffect(() => {
    setBreakdown(null);
    cacheRef.current = null;
  }, [cacheKey]);

  // Prefetch Insights breakdown so header ring can honor capacity_source
  // (DEC-T14 / UI03) even when the popover never opens.
  useEffect(() => {
    if (!agentId || !threadId || isPendingThread(threadId)) return;
    void loadBreakdown({ silent: true });
  }, [agentId, threadId, loadBreakdown]);

  const capacityResolved = isCapacityResolved(
    breakdown?.capacity_source,
    breakdown?.capacity_tokens ?? null,
  );

  const ringUsed = useMemo(() => {
    if (breakdown && breakdown.used_tokens > 0) {
      const cap =
        capacityResolved && breakdown.capacity_tokens
          ? breakdown.capacity_tokens
          : breakdown.max_tokens > 0
            ? breakdown.max_tokens
            : max;
      return Math.min(breakdown.used_tokens, cap);
    }
    if (hintUsed > 0) return Math.min(hintUsed, max);
    return 0;
  }, [breakdown, hintUsed, max, capacityResolved]);

  const ringMax = capacityResolved
    ? (breakdown?.capacity_tokens as number)
    : breakdown && breakdown.max_tokens > 0
      ? breakdown.max_tokens
      : max;

  const { usedPct, strokeColor, dashOffset, circumference } = useMemo(() => {
    const r = 13;
    const circ = 2 * Math.PI * r;
    // DEC-T05 / UI03: no precise occupancy against unresolved capacity.
    const precise = occupancyPercent(
      ringUsed,
      capacityResolved ? ringMax : null,
      breakdown?.capacity_source,
    );
    const usedRatio =
      precise != null && ringMax > 0 ? Math.min(ringUsed / ringMax, 1) : 0;
    let color = "var(--fn-color-success, #22c55e)";
    if (precise != null) {
      if (usedRatio >= 0.8) {
        color = "var(--fn-color-danger, #ef4444)";
      } else if (usedRatio >= 0.5) {
        color = "var(--fn-color-warning, #eab308)";
      }
    }
    return {
      usedPct: precise == null ? null : contextUsedPercent(ringUsed, ringMax),
      strokeColor: color,
      dashOffset: circ * (1 - usedRatio),
      circumference: circ,
    };
  }, [ringUsed, ringMax, capacityResolved, breakdown?.capacity_source]);

  const tooltip = capacityResolved
    ? t("chat.contextWindow.tooltip", {
        used: formatTokenK(ringUsed),
        max: formatTokenK(ringMax),
        percent: usedPct ?? 0,
      })
    : t("chat.contextWindow.tooltipUnknown", {
        used: formatTokenK(ringUsed),
      });

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (next) {
      void loadBreakdown();
    }
  };

  const display = breakdown ?? {
    max_tokens: ringMax,
    used_tokens: ringUsed,
    segments: [] as ContextUsageBreakdown["segments"],
    capacity_source: breakdown?.capacity_source,
    capacity_tokens: breakdown?.capacity_tokens,
  };
  const displayUsed = display.used_tokens > 0 ? display.used_tokens : ringUsed;
  const displayMax =
    capacityResolved && display.capacity_tokens
      ? display.capacity_tokens
      : display.max_tokens > 0
        ? display.max_tokens
        : ringMax;
  const displayPct = occupancyPercent(
    displayUsed,
    capacityResolved ? displayMax : null,
    display.capacity_source ?? breakdown?.capacity_source,
  );
  const segments =
    display.segments.length > 0
      ? display.segments
      : displayUsed > 0
      ? ([
          { key: "conversation", tokens: displayUsed },
        ] as ContextUsageBreakdown["segments"])
      : display.segments;
  const segmentTotal = segments.reduce((sum, item) => sum + item.tokens, 0);

  const popoverContent = (
    <div className={styles.contextUsagePanel}>
      <div className={styles.contextUsageTitle}>
        {t("chat.contextWindow.breakdownTitle")}
      </div>
      <div className={styles.contextUsageSubtitle}>
        {displayPct == null
          ? t("chat.contextWindow.breakdownPercentUnknown")
          : t("chat.contextWindow.breakdownPercent", {
              percent: Math.round(displayPct),
            })}
      </div>
      <div className={styles.contextUsageHint}>
        {t("chat.contextWindow.breakdownHint")}
      </div>
      {loading ? (
        <div className={styles.contextUsageLoading}>
          <Spin size="small" />
        </div>
      ) : (
        <>
          <div
            className={styles.contextUsageBar}
            role="img"
            aria-label={t("chat.contextWindow.breakdownTitle")}
          >
            {segmentTotal > 0 ? (
              segments.map((segment) => (
                <span
                  key={segment.key}
                  className={styles.contextUsageBarSegment}
                  style={{
                    // Provider input usage owns the total bar width. Segment
                    // estimates contribute only their relative composition.
                    flexGrow: (displayUsed * segment.tokens) / segmentTotal,
                    background: SEGMENT_COLORS[segment.key],
                  }}
                />
              ))
            ) : (
              <span
                className={styles.contextUsageBarSegment}
                style={{
                  flexGrow: displayUsed,
                  background: strokeColor,
                }}
              />
            )}
            <span
              className={styles.contextUsageBarRemainder}
              style={{ flexGrow: Math.max(displayMax - displayUsed, 0) }}
            />
          </div>
          <ul className={styles.contextUsageLegend}>
            {segments.map((segment) => (
              <li key={segment.key} className={styles.contextUsageLegendItem}>
                <span
                  className={styles.contextUsageLegendSwatch}
                  style={{ background: SEGMENT_COLORS[segment.key] }}
                />
                <span className={styles.contextUsageLegendLabel}>
                  {t(`chat.contextWindow.segments.${segment.key}`)}
                </span>
                <span className={styles.contextUsageLegendValue}>
                  ~{formatTokenK(segment.tokens)}
                </span>
              </li>
            ))}
            {segments.length === 0 && (
              <li className={styles.contextUsageLegendItem}>
                <span className={styles.contextUsageLegendLabel}>
                  {tooltip}
                </span>
              </li>
            )}
          </ul>
        </>
      )}
    </div>
  );

  const ringInner = (
    <>
      <svg className={styles.contextRingSvg} viewBox="0 0 32 32" aria-hidden>
        <circle
          className={styles.contextRingTrack}
          cx="16"
          cy="16"
          r="13"
          fill="none"
          strokeWidth="3"
        />
        <circle
          className={styles.contextRingProgress}
          cx="16"
          cy="16"
          r="13"
          fill="none"
          strokeWidth="3"
          stroke={strokeColor}
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          strokeLinecap="round"
          transform="rotate(-90 16 16)"
        />
      </svg>
      <span className={styles.contextRingLabel}>
        {usedPct == null ? "—" : usedPct}
      </span>
    </>
  );

  const ring = (
    <div
      className={styles.contextRingBtn}
      role="progressbar"
      aria-valuenow={usedPct ?? undefined}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={tooltip}
    >
      {ringInner}
    </div>
  );

  if (!agentId || !threadId) {
    return ring;
  }

  if (onInspect) {
    return (
      <button
        type="button"
        className={styles.contextRingBtn}
        aria-label={t("chat.contextInspect.title")}
        title={tooltip}
        onClick={onInspect}
      >
        {ringInner}
      </button>
    );
  }

  if (isMobile) {
    return (
      <>
        <button
          type="button"
          className={styles.contextRingBtn}
          onClick={() => handleOpenChange(true)}
          aria-label={tooltip}
        >
          {ringInner}
        </button>
        <Drawer
          open={open}
          onClose={() => handleOpenChange(false)}
          placement="bottom"
          height="auto"
          title={t("chat.contextWindow.breakdownTitle")}
          className={styles.mobilePickerDrawer}
          styles={{
            body: {
              padding: "12px 16px calc(16px + env(safe-area-inset-bottom))",
            },
          }}
          destroyOnHidden
        >
          {popoverContent}
        </Drawer>
      </>
    );
  }

  return (
    <Popover
      content={popoverContent}
      trigger="click"
      open={open}
      onOpenChange={handleOpenChange}
      placement="topRight"
      overlayClassName={styles.contextUsagePopover}
    >
      {ring}
    </Popover>
  );
}
