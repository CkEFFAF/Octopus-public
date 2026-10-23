import type { Session } from "../hooks/useSessions";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import { formatMessageTime } from "../../../utils/formatMessageTime";
import { previewText } from "../utils/sessionPreview";
import SessionActivity from "./SessionActivity";
import SessionPreview from "./SessionPreview";
import styles from "../index.module.less";

export default function SessionRowContent({ session }: { session: Session }) {
  const timezone = useServerTimezone();
  return (
    <span className={styles.sessionRowCopy}>
      <SessionPreview session={session}>
        <span tabIndex={0} className={styles.sessionRowTitle}>
          {previewText(session.name)}
        </span>
      </SessionPreview>
      <span className={styles.sessionRowMeta}>
        <SessionActivity threadId={session.id} />
        {session.updatedAt && (
          <time className={styles.sessionRowTime} dateTime={session.updatedAt}>
            {formatMessageTime(new Date(session.updatedAt).getTime(), timezone)}
          </time>
        )}
      </span>
    </span>
  );
}
