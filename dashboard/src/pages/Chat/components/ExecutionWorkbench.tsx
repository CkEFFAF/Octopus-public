import { useEffect, useState } from "react";
import { Alert, Spin } from "antd";
import { useTranslation } from "react-i18next";
import {
  executionApi,
  type ExecutionContext,
  type ExecutionTarget,
} from "../../../api/modules/execution";
import { showApiError } from "../../../utils/showApiToast";
import NativeDeviceFiles from "../../Devices/NativeDeviceFiles";
import DeviceDesktop from "../../Devices/DeviceDesktop";
import ChatDockGit from "./ChatDockGit";
import ExecutionJobs from "./ExecutionJobs";
import ExecutionTerminal from "./ExecutionTerminal";
import ExecutionBrowser from "./ExecutionBrowser";
import styles from "./ExecutionWorkbench.module.less";

export default function ExecutionWorkbench({
  context,
  surface,
  initialFilePath,
  visible,
}: {
  context: ExecutionContext;
  surface: "workspace" | "git" | "jobs" | "terminal" | "browser" | "desktop";
  initialFilePath?: string;
  visible: boolean;
}) {
  const { t } = useTranslation();
  const [device, setDevice] = useState<ExecutionTarget | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let disposed = false;
    setDevice(null);
    setFailed(false);
    void executionApi
      .target(context.context_id)
      .then((target) => {
        if (disposed) return;
        setDevice(target);
      })
      .catch(() => {
        if (!disposed) setFailed(true);
      });
    return () => {
      disposed = true;
    };
  }, [context.context_id]);
  if (failed) return <Alert type="error" message={t("devices.loadFailed")} />;
  if (!device) return <Spin size="small" />;
  return (
    <div className={styles.root}>
      <header className={styles.target}>
        <strong>
          {context.target_kind === "local"
            ? t("devices.localExecution")
            : device.name}
        </strong>
        <code title={context.working_dir ?? ""}>
          {context.working_dir ?? "—"}
        </code>
        <span>{t(`chat.workMode.${context.work_mode}`)}</span>
      </header>
      <div className={styles.surface}>
        {surface === "workspace" && (
          <NativeDeviceFiles
            device={device}
            executionContext={context}
            initialFilePath={initialFilePath}
            onError={(error) => showApiError(error, t("devices.loadFailed"), t)}
          />
        )}
        {surface === "git" && (
          <ChatDockGit
            agentId=""
            executionContext={context}
            targetName={device.name}
          />
        )}
        {surface === "jobs" && (
          <ExecutionJobs context={context} visible={visible} />
        )}
        {surface === "terminal" && (
          <ExecutionTerminal context={context} visible={visible} />
        )}
        {surface === "browser" && (
          <ExecutionBrowser context={context} visible={visible} />
        )}
        {surface === "desktop" && (
          <DeviceDesktop
            device={device}
            context={context}
            visible={visible}
            onError={(error) => showApiError(error, t("devices.loadFailed"), t)}
          />
        )}
      </div>
    </div>
  );
}
