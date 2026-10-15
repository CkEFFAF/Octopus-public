import { parseKnowledgeCitations } from "./parseKnowledgeCitations";
import type { KnowledgeCitation } from "./parseKnowledgeCitations";
import type { AssistantTurnSplit } from "../pages/Chat/utils/messageContent";
import type { ChatMessage } from "../pages/Chat/hooks/useChat";

export type { KnowledgeCitation };

const messageCitationsCache = new WeakMap<ChatMessage, KnowledgeCitation[]>();

/** Collect unique knowledge citations from tool results in an assistant turn. */
export function collectTurnKnowledgeCitations(
  split: AssistantTurnSplit,
): KnowledgeCitation[] {
  const out: KnowledgeCitation[] = [];
  const seen = new Set<string>();
  for (const msg of split?.tools ?? []) {
    if (msg.toolData?.name !== "search_knowledge") continue;
    let citations = messageCitationsCache.get(msg);
    if (!citations) {
      citations = parseKnowledgeCitations(msg.toolData.output).citations;
      messageCitationsCache.set(msg, citations);
    }
    for (const citation of citations) {
      if (seen.has(citation.docId)) continue;
      seen.add(citation.docId);
      out.push(citation);
    }
  }
  return out;
}
