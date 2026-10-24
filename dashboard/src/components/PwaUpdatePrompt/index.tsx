import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "antd";
import { applyUpdate } from "../../pwa";
import { updateApi } from "../../api/modules/update";
import styles from "./index.module.less";

/**
 * Listens for the "pwa:update-ready" event (dispatched by sw-register.ts) and
 * renders a dismissible banner so the user can choose when to reload.
 * Designed to be mounted once in MainLayout.
 *
 * When the process is running as a system service (OCTOP_SERVICE_MODE is
 * set), clicking the update-now action also triggers a backend service restart so that
 * the new Python package takes effect alongside the new frontend bundle.
 */
export default function PwaUpdatePrompt() {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [modal, contextHolder] = Modal.useModal();

  useEffect(() => {
    const handler = () => setVisible(true);
    window.addEventListener("pwa:update-ready", handler);
    return () => window.removeEventListener("pwa:update-ready", handler);
  }, []);

  if (!visible) return null;

  const handleUpdate = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const status = await updateApi.getUpdateStatus();
      modal.confirm({
        zIndex: 10000,
        title: t("uiFeedback.updateTitle"),
        content: t(
          status.service_mode
            ? "uiFeedback.updateService"
            : "uiFeedback.updatePage",
        ),
        okText: t("pwa.updateNow"),
        cancelText: t("pwa.later"),
        onCancel: () => setBusy(false),
        onOk: async () => {
          try {
            if (status.service_mode) await updateApi.restartService();
            await applyUpdate();
            setBusy(false);
            setVisible(false);
          } catch {
            setError(t("uiFeedback.updateFailed"));
            throw new Error(t("uiFeedback.updateFailed"));
          }
        },
      });
    } catch {
      setError(t("uiFeedback.updateFailed"));
      setBusy(false);
    }
  };

  const handleDismiss = () => setVisible(false);

  return (
    <div className={styles.banner} role="alert" aria-live="polite">
      {contextHolder}
      <span className={styles.icon}>✨</span>
      <span className={styles.text}>{error || t("pwa.updateReady")}</span>
      <button
        className={styles.btnPrimary}
        disabled={busy}
        onClick={() => void handleUpdate()}
      >
        {t("pwa.updateNow")}
      </button>
      <button
        className={styles.btnGhost}
        disabled={busy}
        onClick={handleDismiss}
        aria-label={t("pwa.later")}
      >
        ✕
      </button>
    </div>
  );
}
