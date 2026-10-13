import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Bug,
  Hammer,
  ListTodo,
  MessageCircleQuestion,
  Monitor,
  Network,
  Search,
  Users,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { Popover, Tooltip } from "antd";
import type { ConversationMode } from "../utils/conversationMode";
import { WORK_MODES, type WorkMode } from "../utils/workMode";
import styles from "../index.module.less";

const ICONS: Record<WorkMode, LucideIcon> = {
  agentic: Hammer,
  plan: ListTodo,
  debug: Bug,
  multitask: Workflow,
  cowork: Users,
  computer_use: Monitor,
  deep_research: Search,
  team: Network,
  ask: MessageCircleQuestion,
};

export function workModeIcon(mode: WorkMode): LucideIcon {
  return ICONS[mode];
}

export function ConversationModeMenu({
  conversationMode,
  workMode,
  onChange,
  onWorkModeChange,
}: {
  conversationMode: ConversationMode;
  workMode?: WorkMode;
  onChange: (mode: ConversationMode) => void;
  onWorkModeChange?: (mode: WorkMode) => void;
}) {
  const { t } = useTranslation();
  const selected =
    workMode ?? (conversationMode === "craft" ? "agentic" : conversationMode);
  const select = (mode: WorkMode) => {
    onWorkModeChange?.(mode);
    onChange(mode === "plan" || mode === "ask" ? mode : "craft");
  };
  return (
    <div className={`${styles.modeMenu} ${styles.modeMenuWorkflows}`}>
      {WORK_MODES.map((mode) => {
        const Icon = ICONS[mode];
        return (
          <button
            key={mode}
            type="button"
            className={`${styles.modeMenuItem} ${
              selected === mode ? styles.modeMenuItemActive : ""
            }`}
            onClick={() => select(mode)}
          >
            <span className={styles.modeMenuTitle}>
              <Icon size={16} />
              {t(`chat.workMode.${mode}`)}
            </span>
            <span className={styles.modeMenuHint}>
              {t(`chat.workMode.${mode}Hint`)}
            </span>
          </button>
        );
      })}
    </div>
  );
}

interface ConversationModePickerProps {
  conversationMode: ConversationMode;
  workMode?: WorkMode;
  onChange: (mode: ConversationMode) => void;
  onWorkModeChange?: (mode: WorkMode) => void;
}

export default function ConversationModePicker({
  conversationMode,
  workMode,
  onChange,
  onWorkModeChange,
}: ConversationModePickerProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const selected =
    workMode ?? (conversationMode === "craft" ? "agentic" : conversationMode);
  const Icon = workModeIcon(selected);
  const modeLabel = t(`chat.workMode.${selected}`);

  return (
    <Popover
      trigger="click"
      placement="topLeft"
      open={open}
      onOpenChange={setOpen}
      overlayClassName={styles.modelPopover}
      content={
        <ConversationModeMenu
          conversationMode={conversationMode}
          workMode={selected}
          onWorkModeChange={onWorkModeChange}
          onChange={(mode) => {
            onChange(mode);
            setOpen(false);
          }}
        />
      }
    >
      <Tooltip title={modeLabel} mouseEnterDelay={0.4}>
        <button
          className={`${styles.secondaryBtn} ${
            selected !== "agentic" ? styles.secondaryBtnModelActive : ""
          }`}
          type="button"
          aria-label={`${t("chat.conversationMode.picker")}: ${modeLabel}`}
          data-testid="conversation-mode-picker"
        >
          <Icon size={16} />
        </button>
      </Tooltip>
    </Popover>
  );
}
