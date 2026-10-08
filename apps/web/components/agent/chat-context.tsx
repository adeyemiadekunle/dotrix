import { useRouter } from "@/lib/navigation";
import { createContext, useCallback, useContext, type ReactNode } from "react";

interface ChatState {
  /** Open a conversation (e.g. one a button just started) in the workspace's Chat. */
  show: (threadId: string) => void;
  /** Where Chat about this project starts. */
  href: string;
}

const ChatContext = createContext<ChatState | null>(null);

/** Chat for one project's pages: conversations open in the workspace's Chat, about this project. */
export function ChatProvider({
  workspaceSlug,
  projectKey,
  children,
}: {
  workspaceSlug: string | undefined;
  projectKey: string | undefined;
  children: ReactNode;
}) {
  const router = useRouter();
  const href = workspaceSlug ? `/w/${workspaceSlug}/chat${projectKey ? `?project=${projectKey}` : ""}` : "/";
  const show = useCallback(
    (threadId: string) => {
      if (!workspaceSlug) return;
      router.push(`/w/${workspaceSlug}/chat?project=${projectKey ?? ""}&thread=${threadId}`);
    },
    [router, workspaceSlug, projectKey],
  );
  return <ChatContext value={{ show, href }}>{children}</ChatContext>;
}

export function useChat(): ChatState {
  const chat = useContext(ChatContext);
  if (!chat) throw new Error("useChat needs a ChatProvider");
  return chat;
}
