import { Button, Space, Tabs } from "antd";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import TaskOverview from "../../components/TaskOverview";
import PageShell from "../../layouts/PageShell";
import ScheduleBrowser from "../../components/ScheduleBrowser";

export default function TaskCenterPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  return (
    <PageShell
      title={t("taskCenter.title")}
      subtitle={t("taskCenter.subtitle")}
      actions={
        <Space wrap>
          <Button onClick={() => navigate("/task-board")}>
            {t("octopus.board")}
          </Button>
          <Button onClick={() => navigate("/tasks")}>{t("nav.tasks")}</Button>
        </Space>
      }
    >
      <Tabs
        destroyOnHidden
        items={[
          {
            key: "executions",
            label: t("taskCenter.executions"),
            children: (
              <TaskOverview
                agentId={search.get("agent") || ""}
                threadId={search.get("thread") || ""}
                onScopeChange={(agent, thread) => {
                  const next = new URLSearchParams(search);
                  if (agent) next.set("agent", agent);
                  else next.delete("agent");
                  if (thread) next.set("thread", thread);
                  else next.delete("thread");
                  setSearch(next, { replace: true });
                }}
              />
            ),
          },
          ...["schedules", "reminders"].map((tab) => ({
            key: tab,
            label: t(`workspace0034.${tab}`),
            children: (
              <ScheduleBrowser
                global
                agentId={search.get("agent") || undefined}
                threadId={search.get("thread") || undefined}
                reminder={tab === "reminders"}
              />
            ),
          })),
        ]}
      />
    </PageShell>
  );
}
