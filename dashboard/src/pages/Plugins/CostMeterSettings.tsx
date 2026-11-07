import { useEffect, useState } from "react";
import { Alert, Button, DatePicker, Drawer, Form, Input, Space } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";
import { useTranslation } from "react-i18next";
import {
  pluginMarketApi,
  PLUGIN_MARKET_CHANGED,
} from "../../api/modules/pluginMarket";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { message } from "../../utils/antdMessage";
import { apiErrorMessage } from "../../utils/apiError";

dayjs.extend(utc);
dayjs.extend(timezone);

export default function CostMeterSettings({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const zone = useServerTimezone();
  const userId = useCurrentUser()?.id;
  const [key, setKey] = useState("");
  const [expiry, setExpiry] = useState<Dayjs | null>(null);
  const [configured, setConfigured] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    setKey("");
    setExpiry(null);
    setConfigured(false);
    if (open) {
      setLoading(true);
      setFailed(false);
      void pluginMarketApi
        .state()
        .then((state) => {
          if (!alive) return;
          setConfigured(state.key_configured);
          setExpiry(
            state.subscription_expires_at
              ? dayjs(state.subscription_expires_at).tz(zone)
              : null,
          );
        })
        .catch(() => {
          if (alive) setFailed(true);
        })
        .finally(() => {
          if (alive) setLoading(false);
        });
    }
    return () => {
      alive = false;
    };
  }, [open, zone, userId]);

  const save = async (clear = false) => {
    setBusy(true);
    try {
      await pluginMarketApi.configure({
        ...(clear
          ? { clear_go_api_key: true }
          : key.trim()
          ? { go_api_key: key.trim() }
          : {}),
        subscription_expires_at: expiry
          ? dayjs.tz(expiry.format("YYYY-MM-DD HH:mm:ss"), zone).toISOString()
          : null,
      });
      setKey("");
      window.dispatchEvent(new Event(PLUGIN_MARKET_CHANGED));
      message.success(t("pluginMarket.saved"));
      onClose();
    } catch (error) {
      message.error(apiErrorMessage(error, t("pluginMarket.saveFailed"), t));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer
      open={open}
      onClose={busy ? undefined : onClose}
      title={t("pluginMarket.settingsTitle")}
      width={440}
      destroyOnClose
      extra={
        <Button
          type="primary"
          onClick={() => void save()}
          loading={busy}
          disabled={loading || failed}
        >
          {t("pluginMarket.save")}
        </Button>
      }
    >
      {failed && <Alert type="error" message={t("pluginMarket.loadFailed")} />}
      <Form layout="vertical" disabled={loading || failed || busy}>
        <Alert
          type="info"
          showIcon
          message={t("pluginMarket.privateConfig")}
          style={{ marginBottom: 24 }}
        />
        <Form.Item
          htmlFor="plugin-go-api-key"
          label={t("pluginMarket.apiKey")}
          help={
            configured
              ? t("pluginMarket.keySavedHint")
              : t("pluginMarket.keyHelp")
          }
        >
          <Input.Password
            id="plugin-go-api-key"
            value={key}
            autoComplete="new-password"
            placeholder={configured ? t("pluginMarket.keySaved") : "sk-…"}
            onChange={(event) => setKey(event.target.value)}
          />
        </Form.Item>
        {configured && (
          <Button
            danger
            type="link"
            style={{ paddingLeft: 0, marginBottom: 16 }}
            onClick={() => void save(true)}
          >
            {t("pluginMarket.clearKey")}
          </Button>
        )}
        <Form.Item
          htmlFor="plugin-go-expiry"
          label={t("pluginMarket.expiryLabel", { timezone: zone })}
          help={t("pluginMarket.expiryHelp")}
        >
          <DatePicker
            id="plugin-go-expiry"
            value={expiry}
            onChange={setExpiry}
            showTime
            format="YYYY-MM-DD HH:mm"
            style={{ width: "100%" }}
            placeholder={t("pluginMarket.chooseExpiry")}
          />
        </Form.Item>
        <Space style={{ marginTop: 24 }}>
          <a
            href="https://opencode.ai/console"
            target="_blank"
            rel="noreferrer"
          >
            {t("pluginMarket.openConsole")}
          </a>
        </Space>
      </Form>
    </Drawer>
  );
}
