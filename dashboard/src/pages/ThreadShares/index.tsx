import { useTranslation } from "react-i18next";
import ShareList from "../../components/Sharing/ShareList";
import styles from "../../components/Sharing/sharing.module.less";

export default function ThreadSharesPage() {
  const { t } = useTranslation();
  return (
    <main className={styles.managementPage}>
      <h1>{t("chatShare.allLinks")}</h1>
      <p className={styles.hint}>{t("chatShare.closeExplanation")}</p>
      <ShareList showHeading={false} />
    </main>
  );
}
