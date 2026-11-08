import { Modal } from "antd";
import { useTranslation } from "react-i18next";
import type { TurnFileChange } from "../utils/turnFileChanges";
import FileChangesReview from "./FileChangesReview";
export default function TurnFileChangesModal({
  files,
  onClose,
}: {
  files: TurnFileChange[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Modal
      open
      centered
      title={t("chat.turnChanges.title", { count: files.length })}
      onCancel={onClose}
      footer={null}
      width="min(1200px, calc(100vw - 24px))"
      destroyOnHidden
    >
      <div style={{ height: "70vh", display: "flex" }}>
        <FileChangesReview files={files} current={files} />
      </div>
    </Modal>
  );
}
