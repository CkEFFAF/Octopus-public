import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Empty, Spin, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  connectorsApi,
  type ConnectorInstance,
} from "../../api/modules/connectors";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { CONNECTORS_CHANGED_EVENT } from "../../utils/connectorEvents";
import styles from "./index.module.less";

/** Shared services remain opt-in in expert settings; no credentials are sent here. */
export function SharedMcpMarket() {
  const { t } = useTranslation();
  const user = useCurrentUser();
  const [items, setItems] = useState<ConnectorInstance[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const request = ++requestId.current;
    try {
      const rows = await connectorsApi.listInstances();
      if (request !== requestId.current) return;
      setItems(
        rows.filter(
          (row) =>
            row.kind === "custom-mcp" && row.shared && row.status === "active",
        ),
      );
      setFailed(false);
    } catch {
      if (request === requestId.current) setFailed(true);
    } finally {
      if (request === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const refresh = () => void load();
    window.addEventListener(CONNECTORS_CHANGED_EVENT, refresh);
    return () => {
      requestId.current += 1;
      window.removeEventListener(CONNECTORS_CHANGED_EVENT, refresh);
    };
  }, [load]);

  return (
    <section
      className={styles.market}
      aria-label={t("connectors.sharedMcpMarket.title")}
    >
      <h2>{t("connectors.sharedMcpMarket.title")}</h2>
      <p>{t("connectors.sharedMcpMarket.description")}</p>
      <Button size="small" onClick={() => void load()}>
        {t("common.refresh")}
      </Button>
      {loading ? (
        <Spin />
      ) : failed ? (
        <div role="alert">
          {t("connectors.sharedMcpMarket.loadFailed")}{" "}
          <Button size="small" onClick={() => void load()}>
            {t("common.refresh")}
          </Button>
        </div>
      ) : items.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("connectors.sharedMcpMarket.empty")}
        />
      ) : (
        <div className={styles.grid}>
          {items.map((item) => {
            const unavailable =
              item.transport === "stdio" && user?.role !== "admin";
            return (
              <article key={item.instance_id} className={styles.card}>
                <div className={styles.heading}>
                  <strong>{item.display_name}</strong>
                  <Tag>{item.transport === "stdio" ? "stdio" : "HTTP"}</Tag>
                </div>
                <p>
                  {t("connectors.sharedMcpMarket.publisher", {
                    name:
                      item.owner_display_name ||
                      item.owner_username ||
                      item.owner_user_id,
                  })}
                </p>
                {item.description ? <p>{item.description}</p> : null}
                <p>{t("connectors.sharedMcpMarket.identity")}</p>
                <p>{t("connectors.sharedMcpMarket.unverified")}</p>
                {unavailable ? (
                  <p role="status">
                    {t("connectors.sharedMcpMarket.stdioRestricted")}
                  </p>
                ) : (
                  <Link to="/experts">
                    {t("connectors.sharedMcpMarket.configureExpert")}
                  </Link>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
