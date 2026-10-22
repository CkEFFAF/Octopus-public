import { Modal, Tabs } from "antd";
import { useTranslation } from "react-i18next";
import ScheduleBrowser from "../../../components/ScheduleBrowser";

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
  initialTab?: "schedules" | "reminders";
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
        destroyOnHidden
        title={t("workspace0034.expertTaskPanel")}
      >
        {open && (
          <Tabs
            defaultActiveKey={initialTab}
            items={["schedules", "reminders"].map((tab) => ({
              key: tab,
              label: t(`workspace0034.${tab}`),
              children: (
                <ScheduleBrowser
                  agentId={agentId}
                  threadId={threadId}
                  reminder={tab === "reminders"}
                  onNavigate={onClose}
                />
              ),
            }))}
          />
        )}
      </Modal>
    </div>
  );
}
