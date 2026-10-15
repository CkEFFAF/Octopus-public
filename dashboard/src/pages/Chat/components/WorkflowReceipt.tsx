import { useState } from "react";
import { Alert, Button, Steps, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { executionApi, type RunEvent } from "../../../api/modules/execution";

interface Stage {
  name: string;
  status: string;
  report?: string;
  evidence_ids?: string[];
  decision?: {
    question: string;
    options: string[];
    recommendation: number;
    choice?: number;
  };
}

export default function WorkflowReceipt({
  event,
  agentId,
  threadId,
  onChanged,
}: {
  event: RunEvent;
  agentId: string;
  threadId: string;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const stages = Array.isArray(event.payload.stages)
    ? (event.payload.stages as Stage[])
    : [];
  const current = stages.findIndex((item) => item.status !== "completed");
  return (
    <div>
      <Tag>{t(`chat.workMode.${String(event.payload.mode)}`)}</Tag>
      <Steps
        direction="vertical"
        size="small"
        current={current < 0 ? stages.length : current}
        items={stages.map((stage) => ({
          title: t(`chat.workflow.stages.${stage.name}`, {
            defaultValue: stage.name,
          }),
          status:
            stage.status === "completed"
              ? "finish"
              : stage.status === "blocked"
              ? "error"
              : stage.status === "pending"
              ? "wait"
              : "process",
          description: (
            <div>
              {stage.report && (
                <p style={{ whiteSpace: "pre-wrap" }}>
                  {t("chat.workflow.report")}: {stage.report}
                </p>
              )}
              {!!stage.evidence_ids?.length && (
                <details>
                  <summary>
                    {t("chat.workflow.evidence", {
                      count: stage.evidence_ids.length,
                    })}
                  </summary>
                  <ul>
                    {stage.evidence_ids.map((id) => (
                      <li key={id}>
                        <code>{id}</code>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {stage.decision && (
                <div>
                  <p>{stage.decision.question}</p>
                  {stage.decision.options.map((option, index) =>
                    stage.decision?.choice == null ? (
                      <Button
                        key={index}
                        size="small"
                        disabled={pending}
                        style={{ margin: "0 6px 6px 0" }}
                        onClick={async () => {
                          setPending(true);
                          setError("");
                          try {
                            await executionApi.decide(
                              agentId,
                              threadId,
                              event.event_id,
                              Number(event.payload.version),
                              index,
                            );
                            onChanged();
                          } catch (failure) {
                            setError(
                              failure instanceof Error
                                ? failure.message
                                : t("chat.contextInspect.failed"),
                            );
                          } finally {
                            setPending(false);
                          }
                        }}
                      >
                        {option}
                        {index === stage.decision?.recommendation
                          ? ` · ${t("chat.workflow.recommended")}`
                          : ""}
                      </Button>
                    ) : index === stage.decision.choice ? (
                      <p key={index}>
                        {t("chat.workflow.chosen")}: {option}
                      </p>
                    ) : null,
                  )}
                </div>
              )}
            </div>
          ),
        }))}
      />
      {error && <Alert type="error" message={error} />}
    </div>
  );
}
