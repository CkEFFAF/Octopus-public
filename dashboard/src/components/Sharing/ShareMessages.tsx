import { useTranslation } from "react-i18next";
import type { SharedMessage } from "../../api/modules/threadShares";
import PublicMarkdown from "./PublicMarkdown";
import styles from "./sharing.module.less";

export default function ShareMessages({
  messages,
}: {
  messages: SharedMessage[];
}) {
  const { t } = useTranslation();
  return (
    <div>
      {messages
        .filter(
          (message) =>
            ["user", "assistant"].includes(message.role) &&
            typeof message.content === "string",
        )
        .map((message) => (
          <article className={styles.message} key={message.id}>
            <strong>{t(`chatShare.roles.${message.role}`)}</strong>
            <PublicMarkdown content={message.content} />
          </article>
        ))}
    </div>
  );
}
