import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "./sseHelpers";
import { chatAnimationPhase } from "../utils/expertAnimation";
import {
  lifecyclePhase,
  type ExpertPhase,
} from "../../../components/AnimatedExpertAvatar/model";

export function useExpertAnimation({
  messages,
  running,
  sessionKey,
  state,
  offline,
}: {
  messages: ChatMessage[];
  running: boolean;
  sessionKey: string;
  state?: string;
  offline?: boolean;
}) {
  const previous = useRef({ sessionKey, running });
  const [completed, setCompleted] = useState<string | null>(null);
  const [pausedTurn, setPausedTurn] = useState<string | null>(null);
  const turnKey = `${sessionKey}/${
    messages.filter((m) => m.role === "user").at(-1)?.id ?? ""
  }`;
  const phase = chatAnimationPhase(messages, running);
  useEffect(() => {
    const wasRunning =
      previous.current.sessionKey === sessionKey && previous.current.running;
    previous.current = { sessionKey, running };
    if (wasRunning && !running && phase === "idle") {
      setCompleted(turnKey);
    }
    if (running) setCompleted(null);
    if (running && !wasRunning) setPausedTurn(null);
  }, [sessionKey, running, phase, turnKey]);
  useEffect(() => {
    if (!completed) return;
    const timer = setTimeout(() => setCompleted(null), 2200);
    return () => clearTimeout(timer);
  }, [completed]);
  const lifecycle = lifecyclePhase(state, offline);
  const result: ExpertPhase =
    lifecycle !== "idle"
      ? lifecycle
      : pausedTurn === turnKey
      ? "paused"
      : phase === "idle" && completed === turnKey
      ? "success"
      : phase;
  return { phase: result, pause: () => setPausedTurn(turnKey) };
}
