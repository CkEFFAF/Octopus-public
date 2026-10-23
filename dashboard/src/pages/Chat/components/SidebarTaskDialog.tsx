import { Modal, Tabs } from "antd";
import { useTranslation } from "react-i18next";
import ScheduleBrowser from "../../../components/ScheduleBrowser";
import ExpertTaskSummary from "./ExpertTaskSummary";
import styles from "./ExpertTaskSummary.module.less";

/** Keep sidebar inspection in place, without selecting another conversation. */
export default function SidebarTaskDialog({
  agentId,
  threadId,
  open,
  onClose,
  initialTab = "schedules",
}: {
  agentId: string;
  threadId?: string;
  open: boolean;
  onClose: () => void;
  initialTab?: "schedules" | "reminders" | "background";
}) {
  const { t } = useTranslation();
  return (
    <div
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
    >
      <Modal
        open={open}
        onCancel={onClose}
        footer={null}
        width={840}
        className={styles.taskDialog}
        destroyOnHidden
        title={t("workspace0034.expertTaskPanel")}
      >
        {open && (
          <Tabs
            defaultActiveKey={threadId ? initialTab : "background"}
            items={[
              {
                key: "background",
                label: t("workspace0034.backgroundSummary"),
                children: (
                  <ExpertTaskSummary agentId={agentId} threadId={threadId} />
                ),
              },
              ...["schedules", "reminders"].map((tab) => ({
                key: tab,
                label: t(`workspace0034.${tab}`),
                children: (
                  <ScheduleBrowser
                    compact
                    agentId={agentId}
                    threadId={threadId}
                    reminder={tab === "reminders"}
                    onNavigate={onClose}
                  />
                ),
              })),
            ]}
          />
        )}
      </Modal>
    </div>
  );
}
