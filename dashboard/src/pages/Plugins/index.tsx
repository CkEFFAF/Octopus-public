import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Alert,
  Button,
  Empty,
  Input,
  Popconfirm,
  Spin,
  Switch,
  Tabs,
  Tag,
} from "antd";
import {
  Check,
  Download,
  ExternalLink,
  Gauge,
  Puzzle,
  Search,
  Settings2,
  Store,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import PageShell from "../../layouts/PageShell";
import {
  pluginMarketApi,
  PLUGIN_MARKET_CHANGED,
  type CatalogPlugin,
} from "../../api/modules/pluginMarket";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { userCan } from "../../utils/permissions";
import { message } from "../../utils/antdMessage";
import { apiErrorMessage } from "../../utils/apiError";
import CostMeter from "./CostMeter";
import CostMeterSettings from "./CostMeterSettings";
import styles from "./index.module.less";

export default function PluginsPage() {
  const { t } = useTranslation();
  const user = useCurrentUser();
  const userId = user?.id;
  const ownerRef = useRef(userId);
  ownerRef.current = userId;
  const [catalogOwner, setCatalogOwner] = useState<number | null>(null);
  const [params, setParams] = useSearchParams();
  const [items, setItems] = useState<CatalogPlugin[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [settings, setSettings] = useState(false);
  const tab = params.get("tab") === "installed" ? "installed" : "market";

  const load = useCallback(async () => {
    if (userId == null) return;
    try {
      const catalog = await pluginMarketApi.catalog();
      if (ownerRef.current !== userId) return;
      setItems(catalog);
      setFailed(false);
    } catch {
      if (ownerRef.current === userId) setFailed(true);
    } finally {
      if (ownerRef.current === userId) {
        setCatalogOwner(userId);
        setLoading(false);
      }
    }
  }, [userId]);
  useEffect(() => {
    setLoading(true);
    setSettings(false);
    void load();
  }, [load]);
  const change = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
      await load();
      window.dispatchEvent(new Event(PLUGIN_MARKET_CHANGED));
    } catch (error) {
      message.error(apiErrorMessage(error, t("pluginMarket.actionFailed"), t));
    } finally {
      setBusy(false);
    }
  };
  const visibleItems = catalogOwner === userId ? items : [];
  const matching = visibleItems.filter((item) =>
    `${item.name} ${item.id} ${item.description} ${t(
      "pluginMarket.costDescription",
    )}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );
  const installed = visibleItems.filter((item) => item.installed);
  const openSettings = () => setSettings(true);
  return (
    <PageShell
      title={t("pluginMarket.title")}
      subtitle={t("pluginMarket.subtitle")}
      actions={
        userCan(user, "plugins") ? (
          <Link to="/admin/plugins">
            <Button icon={<Settings2 size={14} />}>
              {t("pluginMarket.serverPlugins")}
            </Button>
          </Link>
        ) : undefined
      }
    >
      <Tabs
        activeKey={tab}
        onChange={(key) => setParams(key === "installed" ? { tab: key } : {})}
        items={[
          {
            key: "market",
            label: (
              <span className={styles.tabLabel}>
                <Store size={15} />
                {t("pluginMarket.market")}
              </span>
            ),
            children: (
              <>
                <div className={styles.toolbar}>
                  <span>
                    {t("pluginMarket.catalogCount", { count: items.length })}
                  </span>
                  <Input
                    prefix={<Search size={14} />}
                    allowClear
                    placeholder={t("pluginMarket.search")}
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                  />
                </div>
                {loading ? (
                  <div className={styles.loading}>
                    <Spin />
                  </div>
                ) : failed ? (
                  <Alert
                    type="error"
                    message={t("pluginMarket.loadFailed")}
                    action={
                      <Button onClick={() => void load()}>
                        {t("pluginMarket.retry")}
                      </Button>
                    }
                  />
                ) : matching.length === 0 ? (
                  <Empty description={t("pluginMarket.noResults")} />
                ) : (
                  <div className={styles.catalogGrid}>
                    {matching.map((item) => (
                      <article className={styles.pluginCard} key={item.id}>
                        <div className={styles.pluginIdentity}>
                          <span className={styles.pluginIcon}>
                            <Gauge size={26} strokeWidth={1.6} />
                          </span>
                          <div>
                            <h2>{item.name}</h2>
                            <span>
                              {t("pluginMarket.costName")}{" "}
                              <Tag bordered={false}>v{item.version}</Tag>
                            </span>
                          </div>
                        </div>
                        <p className={styles.description}>
                          {t("pluginMarket.costDescription")}
                        </p>
                        <div
                          className={styles.preview}
                          aria-label={t("pluginMarket.previewLabel")}
                        >
                          <div>
                            <span className={styles.previewDot} />
                            DeepSeek{" "}
                            <strong>{t("pluginMarket.peakAndOffpeak")}</strong>
                          </div>
                          <div>
                            <span className={styles.miniGo}>Go</span>
                            <span>
                              {t("pluginMarket.rollingShort")}
                              <b>—</b>
                            </span>
                            <span>
                              {t("pluginMarket.weekly")}
                              <b>—</b>
                            </span>
                            <span>
                              {t("pluginMarket.monthly")}
                              <b>—</b>
                            </span>
                          </div>
                          <small>{t("pluginMarket.previewNote")}</small>
                        </div>
                        <div className={styles.features}>
                          <Tag bordered={false}>
                            {t("pluginMarket.liveClock")}
                          </Tag>
                          <Tag bordered={false}>
                            {t("pluginMarket.quotaTracking")}
                          </Tag>
                          <Tag bordered={false}>
                            {t("pluginMarket.subscription")}
                          </Tag>
                        </div>
                        <footer className={styles.cardFooter}>
                          <a
                            href={item.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {t("pluginMarket.reference")}
                            <ExternalLink size={12} />
                          </a>
                          {item.installed ? (
                            <Button
                              icon={<Check size={14} />}
                              onClick={() => setParams({ tab: "installed" })}
                            >
                              {t("pluginMarket.open")}
                            </Button>
                          ) : (
                            <Button
                              type="primary"
                              loading={busy}
                              icon={<Download size={14} />}
                              onClick={() =>
                                void change(async () => {
                                  await pluginMarketApi.install(item.id);
                                  setParams({ tab: "installed" });
                                })
                              }
                            >
                              {t("pluginMarket.install")}
                            </Button>
                          )}
                        </footer>
                      </article>
                    ))}
                  </div>
                )}
                <p className={styles.sharingNote}>
                  <Puzzle size={14} />
                  {t("pluginMarket.sharingNote")}
                </p>
              </>
            ),
          },
          {
            key: "installed",
            label: (
              <span className={styles.tabLabel}>
                <Puzzle size={15} />
                {t("pluginMarket.myPlugins")}
                <span className={styles.countBadge}>{installed.length}</span>
              </span>
            ),
            children: loading ? (
              <Spin />
            ) : failed ? (
              <Alert
                type="error"
                message={t("pluginMarket.loadFailed")}
                action={
                  <Button onClick={() => void load()}>
                    {t("pluginMarket.retry")}
                  </Button>
                }
              />
            ) : installed.length === 0 ? (
              <Empty description={t("pluginMarket.noInstalled")}>
                <Button type="primary" onClick={() => setParams({})}>
                  {t("pluginMarket.browse")}
                </Button>
              </Empty>
            ) : (
              <>
                {installed.map((item) => (
                  <section className={styles.installedPlugin} key={item.id}>
                    <div className={styles.installedHeader}>
                      <div>
                        <Gauge size={20} />
                        <strong>{item.name}</strong>
                        <Tag
                          color={item.enabled ? "success" : "default"}
                          bordered={false}
                        >
                          {t(
                            item.enabled
                              ? "pluginMarket.enabled"
                              : "pluginMarket.disabled",
                          )}
                        </Tag>
                      </div>
                      <div>
                        <Button
                          icon={<Settings2 size={14} />}
                          onClick={openSettings}
                        >
                          {t("pluginMarket.configure")}
                        </Button>
                        <Switch
                          checked={item.enabled}
                          loading={busy}
                          aria-label={t("pluginMarket.enablePlugin")}
                          onChange={(enabled) =>
                            void change(() =>
                              pluginMarketApi.install(
                                item.id,
                                enabled,
                                item.show_in_chat,
                              ),
                            )
                          }
                        />
                        <Popconfirm
                          title={t("pluginMarket.uninstallConfirm")}
                          description={t("pluginMarket.uninstallDescription")}
                          onConfirm={() =>
                            change(() => pluginMarketApi.uninstall(item.id))
                          }
                        >
                          <Button
                            type="text"
                            danger
                            icon={<Trash2 size={15} />}
                            aria-label={t("pluginMarket.uninstall")}
                            disabled={busy}
                          />
                        </Popconfirm>
                      </div>
                    </div>
                    {item.enabled ? (
                      <>
                        <CostMeter onSettings={openSettings} />
                        <div className={styles.dockSetting}>
                          <div>
                            <strong>{t("pluginMarket.showInChat")}</strong>
                            <small>{t("pluginMarket.showInChatHint")}</small>
                          </div>
                          <Switch
                            checked={item.show_in_chat}
                            loading={busy}
                            aria-label={t("pluginMarket.showInChat")}
                            onChange={(show) =>
                              void change(() =>
                                pluginMarketApi.install(
                                  item.id,
                                  item.enabled,
                                  show,
                                ),
                              )
                            }
                          />
                        </div>
                      </>
                    ) : (
                      <Alert
                        type="info"
                        message={t("pluginMarket.disabledHint")}
                      />
                    )}
                  </section>
                ))}
              </>
            ),
          },
        ]}
      />
      <CostMeterSettings
        key={userId}
        open={settings}
        onClose={() => setSettings(false)}
      />
    </PageShell>
  );
}
