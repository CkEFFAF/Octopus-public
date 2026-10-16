import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Avatar,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import {
  Activity,
  KanbanSquare,
  MessageSquare,
  Plus,
  Settings2,
  Users,
} from "lucide-react";
import { teamsApi, type TeamRecord } from "../../api/modules/teams";
import { taskBoardApi, type BoardSnapshot } from "../../api/modules/taskBoard";
import EditAgentDrawer from "../Experts/components/EditAgentDrawer";
import { useAgent, type OctopAgent } from "../../context/AgentContext";
import { apiErrorMessage } from "../../utils/apiError";
import PageShell from "../../layouts/PageShell";
import { ExpertIcon } from "../Experts/components/iconForName";

export default function ProjectsPage() {
  const { t } = useTranslation();
  const tr = (key: string) => t(`octopus.${key}`);
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { agents, setActiveAgent, refresh } = useAgent();
  const [teams, setTeams] = useState<TeamRecord[]>([]);
  const [board, setBoard] = useState<BoardSnapshot | null>(null);
  const [error, setError] = useState("");
  const [editingExpert, setEditingExpert] = useState<OctopAgent | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  const team =
    teams.find((item) => item.team_id === params.get("project")) || teams[0];
  const ownExperts = agents.filter(
    (agent) => agent.kind !== "team" && agent.is_owner !== false,
  );
  const load = useCallback(async () => {
    try {
      const [rooms, tasks] = await Promise.all([
        teamsApi.list(),
        taskBoardApi.get(),
      ]);
      setTeams(rooms);
      setBoard(tasks);
      setError("");
    } catch (err) {
      setError(apiErrorMessage(err, t("octopus.loadFailed"), t));
    }
  }, [t]);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [load]);
  function edit(item?: TeamRecord) {
    form.resetFields();
    form.setFieldsValue(item || { member_ids: [] });
    setEditing(item?.team_id || "new");
  }
  useEffect(() => {
    if (params.get("new") === "1") {
      edit();
      setParams({}, { replace: true });
    } else if (params.get("edit") === "1") {
      const current = teams.find(
        (item) => item.team_id === params.get("project"),
      );
      if (current) {
        edit(current);
        setParams({ project: current.team_id }, { replace: true });
      }
    }
  }, [params, teams]);
  async function save() {
    const value = await form.validateFields().catch(() => null);
    if (!value) return;
    setSaving(true);
    try {
      const room =
        editing === "new"
          ? await teamsApi.create(value)
          : await teamsApi.update(editing!, value);
      await refresh();
      await load();
      setParams({ project: room.team_id });
      setEditing(null);
    } catch (err) {
      setError(apiErrorMessage(err, tr("actionFailed"), t));
    } finally {
      setSaving(false);
    }
  }
  function goAgent(id: string, path: string) {
    setActiveAgent(id);
    navigate(path);
  }
  const tasks =
    board?.tasks.filter(
      (item) => item.project_id === team?.team_id && !item.archived,
    ) || [];
  return (
    <PageShell
      title={tr("projects")}
      subtitle={tr("projectsHelp")}
      actions={
        <Button type="primary" icon={<Plus size={16} />} onClick={() => edit()}>
          {tr("newProject")}
        </Button>
      }
    >
      {error && (
        <Alert
          type="error"
          showIcon
          message={error}
          closable
          onClose={() => setError("")}
          style={{ marginBottom: 20 }}
        />
      )}
      {!teams.length ? (
        <Empty description={tr("noProjects")}>
          <Button onClick={() => navigate("/experts")}>
            {tr("prepareMembers")}
          </Button>
        </Empty>
      ) : (
        <>
          <Space wrap style={{ marginBottom: 24 }}>
            {teams.map((item) => (
              <Button
                key={item.team_id}
                type={team?.team_id === item.team_id ? "primary" : "default"}
                onClick={() => setParams({ project: item.team_id })}
              >
                {item.name}
              </Button>
            ))}
          </Space>
          {team && (
            <>
              <div
                style={{
                  display: "flex",
                  gap: 20,
                  alignItems: "center",
                  flexWrap: "wrap",
                  marginBottom: 24,
                }}
              >
                <Avatar
                  size={60}
                  src={team.icon_url}
                  style={{ background: team.color || "#7471cf" }}
                  icon={<Users />}
                />
                <div style={{ flex: 1 }}>
                  <Typography.Title level={3} style={{ margin: 0 }}>
                    {team.name}
                  </Typography.Title>
                  <Typography.Text type="secondary">
                    {team.description || tr("groupChat")} ·{" "}
                    {team.members.length} {tr("members")}
                  </Typography.Text>
                </div>
                <Space wrap>
                  <Button
                    onClick={() => edit(team)}
                    icon={<Settings2 size={15} />}
                  >
                    {tr("manageMembers")}
                  </Button>
                  <Button
                    onClick={() =>
                      navigate(`/task-board?project=${team.team_id}`)
                    }
                    icon={<KanbanSquare size={15} />}
                  >
                    {tr("board")}
                  </Button>
                  <Button
                    type="primary"
                    onClick={() =>
                      goAgent(team.agent_id, `/chat/${team.agent_id}`)
                    }
                    icon={<MessageSquare size={15} />}
                  >
                    {tr("groupChat")}
                  </Button>
                </Space>
              </div>
              <Alert message={tr("groupHelp")} style={{ marginBottom: 24 }} />
              <Typography.Title level={5}>{tr("members")}</Typography.Title>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill,minmax(250px,1fr))",
                  gap: 14,
                }}
              >
                {team.members.map((member) => (
                  <Card key={member.agent_id} size="small">
                    <Space>
                      <Avatar
                        src={
                          member.icon_url ? (
                            <ExpertIcon
                              iconUrl={member.icon_url}
                              size={32}
                              phase={member.busy ? "running" : "idle"}
                            />
                          ) : undefined
                        }
                        style={{ background: member.color || "#7471cf" }}
                      >
                        {member.name[0]}
                      </Avatar>
                      <div>
                        <strong>{member.name}</strong>
                        <div>
                          <Typography.Text type="secondary">
                            {agents.find(
                              (agent) => agent.agent_id === member.agent_id,
                            )?.description || member.agent_id}
                          </Typography.Text>
                        </div>
                      </div>
                      <Tag color={member.busy ? "processing" : "default"}>
                        {t(member.busy ? "octopus.executing" : "octopus.idle")}
                      </Tag>
                    </Space>
                    <Space wrap style={{ marginTop: 16 }}>
                      <Button
                        size="small"
                        onClick={() =>
                          goAgent(member.agent_id, `/chat/${member.agent_id}`)
                        }
                      >
                        {tr("privateChat")}
                      </Button>
                      <Button
                        size="small"
                        onClick={() =>
                          setEditingExpert(
                            agents.find(
                              (agent) => agent.agent_id === member.agent_id,
                            ) ??
                              ({
                                agent_id: member.agent_id,
                                name: member.name,
                                state: member.state ?? "stopped",
                                is_owner: false,
                                user_id: member.user_id,
                                config: {},
                              } as OctopAgent),
                          )
                        }
                      >
                        {tr("configuration")}
                      </Button>
                      <Button
                        size="small"
                        onClick={() => goAgent(member.agent_id, "/token-usage")}
                        icon={<Activity size={12} />}
                      >
                        {tr("usage")}
                      </Button>
                    </Space>
                  </Card>
                ))}
              </div>
              <Typography.Title level={5} style={{ marginTop: 28 }}>
                {tr("projectTasks")} ·{" "}
                {tasks.filter((item) => item.status === "done").length}/
                {tasks.length}
              </Typography.Title>
              {!tasks.length ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={tr("noTasks")}
                />
              ) : (
                tasks.slice(0, 8).map((item) => (
                  <div
                    key={item.id}
                    style={{
                      padding: "12px 0",
                      borderBottom: "1px solid var(--fn-border-color,#e8e9ed)",
                    }}
                  >
                    <Tag>{tr(item.status)}</Tag>
                    {item.title}
                  </div>
                ))
              )}
              <Button
                type="link"
                onClick={() => navigate(`/task-board?project=${team.team_id}`)}
              >
                {tr("openBoard")}
              </Button>
            </>
          )}
        </>
      )}
      <EditAgentDrawer
        defaultsOnly
        open={editingExpert !== null}
        agent={editingExpert}
        onClose={() => setEditingExpert(null)}
        onSaved={() => {
          void refresh({ silent: true, force: true });
          void load();
        }}
      />
      <Modal
        title={tr(editing === "new" ? "newProject" : "manageMembers")}
        open={Boolean(editing)}
        onCancel={() => setEditing(null)}
        onOk={() => void save()}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={tr("projectName")}
            rules={[{ required: true, whitespace: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="description" label={tr("description")}>
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item
            name="member_ids"
            label={tr("members")}
            rules={[
              {
                type: "array",
                min: 2,
                required: true,
                message: tr("twoMembers"),
              },
            ]}
          >
            <Select
              mode="multiple"
              options={ownExperts.map((agent) => ({
                value: agent.agent_id,
                label: agent.name,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </PageShell>
  );
}
