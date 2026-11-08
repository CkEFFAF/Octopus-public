import {
  createContext,
  useContext,
  useMemo,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import type { TurnFileChange } from "./utils/turnFileChanges";
import type { KnowledgeCitation } from "../../utils/parseKnowledgeCitations";

interface ChatFilePreviewContextValue {
  openFileChanges?: (files: TurnFileChange[]) => void;
  /** Open the shared file panel on a workspace path (preview / download cards). */
  openFilePreview: (
    path: string,
    agentId?: string | null,
    source?: "workspace",
  ) => void;
  /** Open a knowledge citation in the shared chat dock (same shell as file tabs). */
  openKnowledgeCitation: (citation: KnowledgeCitation) => void;
}

const ChatFilePreviewContext =
  createContext<ChatFilePreviewContextValue | null>(null);
const ChatFileChangesContext = createContext<{
  history: TurnFileChange[];
  current: TurnFileChange[];
  threadId?: string | null;
} | null>(null);
export function useChatFileChanges() {
  return useContext(ChatFileChangesContext);
}

export function ChatFilePreviewProvider({
  openFilePreview,
  openKnowledgeCitation,
  history,
  latest,
  turnId,
  threadId,
  openFileList,
  children,
}: {
  openFilePreview: ChatFilePreviewContextValue["openFilePreview"];
  openKnowledgeCitation: (citation: KnowledgeCitation) => void;
  history?: TurnFileChange[];
  latest?: TurnFileChange[];
  turnId?: string;
  threadId?: string | null;
  openFileList?: () => void;
  children: ReactNode;
}) {
  const [selectedTurn, setSelectedTurn] = useState<TurnFileChange[] | null>(
    null,
  );
  useEffect(() => setSelectedTurn(null), [turnId]);
  const openFileChanges = useCallback(
    (files: TurnFileChange[]) => {
      setSelectedTurn(files);
      openFileList?.();
    },
    [openFileList],
  );
  const fileChanges = useMemo(
    () =>
      history
        ? { history, current: selectedTurn ?? latest ?? [], threadId }
        : null,
    [history, selectedTurn, latest, threadId],
  );
  const value = useMemo(
    () => ({
      openFilePreview,
      openKnowledgeCitation,
      openFileChanges: openFileList ? openFileChanges : undefined,
    }),
    [openFilePreview, openKnowledgeCitation, openFileList, openFileChanges],
  );
  return (
    <ChatFilePreviewContext.Provider value={value}>
      <ChatFileChangesContext.Provider value={fileChanges}>
        {children}
      </ChatFileChangesContext.Provider>
    </ChatFilePreviewContext.Provider>
  );
}

export function useChatFilePreview(): ChatFilePreviewContextValue | null {
  return useContext(ChatFilePreviewContext);
}
