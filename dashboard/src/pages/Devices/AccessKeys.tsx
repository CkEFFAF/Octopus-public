import { useEffect, useState } from "react";
import { App, Button, Checkbox, Input, Modal, Select, Tag } from "antd";
import { KeyRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import { authApi, type AccountAccessKey } from "../../api/modules/auth";
import { apiErrorMessage } from "../../utils/apiError";
import { copyText } from "../../utils/copyText";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../utils/formatMessageTime";

export default function AccessKeys() {
  const { t } = useTranslation();
  const { message, modal } = App.useApp();
  const timezone = useServerTimezone();
  const [open, setOpen] = useState(false);
  const [keys, setKeys] = useState<AccountAccessKey[]>([]);
  const [name, setName] = useState("");
  const [days, setDays] = useState(30);
  const [browser, setBrowser] = useState(true);
  const [devices, setDevices] = useState(true);
  const [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState("");
  const fail = (error: unknown) =>
    message.error(apiErrorMessage(error, t("devices.failed"), t));
  const refresh = async () => setKeys((await authApi.accessKeys()).keys);
  useEffect(() => {
    if (open)
      void authApi
        .accessKeys()
        .then((data) => setKeys(data.keys))
        .catch(fail);
    // Modal opening refreshes the list; locale changes do not refetch credentials.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const close = () => {
    setOpen(false);
    setSecret("");
  };
  return (
    <>
      <Button
        type="text"
        icon={<KeyRound size={16} />}
        onClick={() => setOpen(true)}
      >
        {t("devices.accessKeys.title")}
      </Button>
      <Modal
        title={t("devices.accessKeys.title")}
        open={open}
        onCancel={close}
        footer={
          <Button onClick={close}>{t("devices.accessKeys.close")}</Button>
        }
        width={640}
        destroyOnClose
      >
        <div className="devices-tool devices-pairing">
          <p>{t("devices.accessKeys.hint")}</p>
          <label className="devices-field">
            <span>{t("devices.accessKeys.name")}</span>
            <Input
              maxLength={120}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="devices-field">
            <span>{t("devices.accessKeys.expiry")}</span>
            <Select
              value={days}
              onChange={setDays}
              options={[1, 7, 30, 90, 365].map((value) => ({
                value,
                label: t("devices.accessKeys.days", { count: value }),
              }))}
            />
          </label>
          <Checkbox
            checked={browser}
            onChange={(event) => setBrowser(event.target.checked)}
          >
            {t("devices.accessKeys.browser")}
          </Checkbox>
          <Checkbox
            checked={devices}
            onChange={(event) => setDevices(event.target.checked)}
          >
            {t("devices.accessKeys.devices")}
          </Checkbox>
          <Button
            type="primary"
            loading={busy}
            disabled={!name.trim() || !(browser || devices)}
            onClick={() =>
              modal.confirm({
                title: t("devices.accessKeys.create"),
                content: t("devices.accessKeys.warning"),
                onOk: async () => {
                  setBusy(true);
                  try {
                    const created = await authApi.createAccessKey({
                      name: name.trim(),
                      days,
                      allow_browser: browser,
                      allow_devices: devices,
                    });
                    setSecret(created.secret);
                    await refresh();
                  } catch (error) {
                    fail(error);
                  } finally {
                    setBusy(false);
                  }
                },
              })
            }
          >
            {t("devices.accessKeys.create")}
          </Button>
          {secret && (
            <div className="devices-tool">
              <strong>{t("devices.accessKeys.once")}</strong>
              <code className="devices-pairing-code">{secret}</code>
              <Button
                onClick={async () => {
                  if (await copyText(secret))
                    message.success(t("devices.copied"));
                }}
              >
                {t("devices.accessKeys.copy")}
              </Button>
              <p>{t("devices.accessKeys.clientHint")}</p>
              <pre>
                start-device.bat --server HTTPS_URL --key-file "KEY_FILE"
                --share "SHARED_DIR"
              </pre>
              <p>{t("devices.accessKeys.mobileHint")}</p>
            </div>
          )}
          {keys.map((key) => (
            <div className="devices-operation" key={key.key_id}>
              <div>
                <strong>{key.name}</strong>
                {key.allow_browser > 0 && (
                  <Tag>{t("devices.accessKeys.browser")}</Tag>
                )}
                {key.allow_devices > 0 && (
                  <Tag>{t("devices.accessKeys.devices")}</Tag>
                )}
              </div>
              <span>
                {t("devices.accessKeys.validUntil", {
                  time: formatServerDateTime(key.expires_at, timezone),
                })}
              </span>
              {key.revoked_at !== null ? (
                <Tag>{t("devices.accessKeys.revoked")}</Tag>
              ) : (
                <Button
                  danger
                  onClick={() =>
                    modal.confirm({
                      title: t("devices.accessKeys.revoke"),
                      content: t("devices.accessKeys.revokeHint"),
                      onOk: async () => {
                        try {
                          await authApi.revokeAccessKey(key.key_id);
                          setSecret("");
                          await refresh();
                        } catch (error) {
                          fail(error);
                        }
                      },
                    })
                  }
                >
                  {t("devices.accessKeys.revoke")}
                </Button>
              )}
            </div>
          ))}
        </div>
      </Modal>
    </>
  );
}
