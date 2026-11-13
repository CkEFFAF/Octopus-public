import { useCallback, useState } from "react";

interface RecordingSkill {
  name: string;
  content: string;
  recordingId: string | null;
}

export function usePendingRecordingSkill(
  agentId: string | null,
  threadId: string | null,
) {
  const scope =
    agentId && threadId ? JSON.stringify([agentId, threadId]) : null;
  const [skills, setSkills] = useState(() => new Map<string, RecordingSkill>());
  const setPending = useCallback(
    (skill: RecordingSkill | null) => {
      if (!scope) return;
      setSkills((previous) => {
        const next = new Map(previous);
        if (skill) next.set(scope, skill);
        else next.delete(scope);
        return next;
      });
    },
    [scope],
  );
  return [scope ? skills.get(scope) : undefined, setPending] as const;
}
