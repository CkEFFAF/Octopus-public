import { useState } from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import {
  threadSharesApi,
  type SharePreview,
  type ThreadShare,
} from "../../api/modules/threadShares";
import { copyText } from "../../utils/copyText";
import ChatTitleBar from "../../pages/Chat/components/ChatTitleBar";
import ChatSidebarPanel from "../../pages/Chat/components/ChatSidebarPanel";
import type { Session } from "../../pages/Chat/hooks/useSessions";
import type { OctopAgent } from "../../context/AgentContext";
import ShareManagementDialog from "./ShareManagementDialog";
import ThreadSharesPage from "../../pages/ThreadShares";
import PublicMarkdown from "./PublicMarkdown";
import { buildNavSections } from "../../layouts/sidebarNav";
import en from "../../locales/en.json";
import zh from "../../locales/zh.json";

vi.mock("../../api/modules/threadShares", () => ({
  threadSharesApi: {
    preview: vi.fn(),
    create: vi.fn(),
    list: vi.fn(),
    revoke: vi.fn(),
  },
}));
vi.mock("../../utils/copyText", () => ({ copyText: vi.fn() }));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("../../pages/Chat/hooks/useHiddenSharedExperts", () => ({
  useHiddenSharedExperts: () => ({
    filterVisible: (rows: unknown) => rows,
    pickHidden: () => [],
    canHide: () => false,
    hide: vi.fn(),
    unhide: vi.fn(),
  }),
}));
vi.mock("../../api/modules/octopThreads", () => ({
  octopThreadsApi: { list: vi.fn().mockResolvedValue([]) },
}));

const preview: SharePreview = {
  preview_digest: "reviewed-digest",
  title: "Reviewed snapshot",
  timezone: "Asia/Shanghai",
  messages: [
    { id: 1, role: "user", content: "Public question" },
    { id: 2, role: "assistant", content: "Public answer" },
    { id: 3, role: "assistant", content: "Public answer" },
  ],
  message_count: 3,
};
const share: ThreadShare = {
  share_id: "share-1",
  public_url: "https://configured.example/share/synthetic-link",
  public_path: "/share/synthetic-link",
  title: preview.title,
  agent_id: "expert",
  thread_id: "thread",
  created_at: Date.now() / 1000,
  expires_at: Date.now() / 1000 + 30 * 86400,
  revoked_at: null,
  status: "active",
  message_count: 3,
};
const session: Session = {
  id: "thread",
  threadId: "thread",
  name: "Private conversation",
  updatedAt: null,
  channelType: "web",
  hasActivity: true,
};
const noop = () => {};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(threadSharesApi.preview).mockResolvedValue(preview);
  vi.mocked(threadSharesApi.list).mockResolvedValue({
    shares: [],
    next_before: null,
    has_more: false,
  });
  vi.mocked(threadSharesApi.revoke).mockResolvedValue();
  vi.mocked(copyText).mockResolvedValue(true);
});

function DesktopJourney() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <ChatTitleBar
        session={session}
        title={session.name}
        onRename={noop}
        onPin={noop}
        onFork={noop}
        onDelete={noop}
        onShare={() => setOpen(true)}
      />
      {open && (
        <ShareManagementDialog
          agentId="expert"
          threadId="thread"
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

it("opens desktop share preview, creates exactly its digest with default expiry, recopies and closes the published link", async () => {
  const user = userEvent.setup();
  vi.mocked(threadSharesApi.create).mockImplementation(async () => {
    vi.mocked(threadSharesApi.list).mockResolvedValue({
      shares: [share],
      next_before: null,
      has_more: false,
    });
    return share;
  });
  render(
    <MemoryRouter>
      <DesktopJourney />
    </MemoryRouter>,
  );
  await user.click(screen.getByRole("button", { name: "更多" }));
  const shareMenuItem = await screen.findByRole("menuitem", {
    name: "chatShare.title",
  });
  expect(shareMenuItem.querySelector("svg.lucide-share-2")).toBeInTheDocument();
  await user.click(shareMenuItem);
  const dialog = await screen.findByRole("dialog");
  expect(
    await within(dialog).findByText("Public question"),
  ).toBeInTheDocument();
  expect(within(dialog).getAllByText("Public answer")).toHaveLength(2);
  expect(threadSharesApi.create).not.toHaveBeenCalled();
  await user.click(
    within(dialog).getByRole("button", { name: "chatShare.create" }),
  );
  expect(threadSharesApi.create).toHaveBeenCalledWith(
    "expert",
    "thread",
    preview.preview_digest,
    30 * 86400,
  );
  expect(
    await within(dialog).findByDisplayValue(share.public_url!),
  ).toBeInTheDocument();
  await user.click(
    within(dialog).getByRole("button", { name: "chatShare.copy" }),
  );
  expect(copyText).toHaveBeenCalledWith(share.public_url);
  await user.click(
    within(dialog).getByRole("button", { name: "chatShare.close" }),
  );
  await waitFor(() =>
    expect(threadSharesApi.revoke).toHaveBeenCalledWith("share-1"),
  );
  expect(
    await within(dialog).findByText(/chatShare.status.revoked/),
  ).toBeInTheDocument();
  expect(
    within(dialog).queryByRole("button", { name: "chatShare.copy" }),
  ).not.toBeInTheDocument();
  expect(
    within(dialog).queryByDisplayValue(share.public_url!),
  ).not.toBeInTheDocument();
});

it("rejects stale preview, requires an explicit refreshed review and submits the new digest with no automatic expiry", async () => {
  const user = userEvent.setup();
  vi.mocked(threadSharesApi.create)
    .mockRejectedValueOnce(
      new Error('Request failed: 409 - {"error":{"code":"SHARE_STALE"}}'),
    )
    .mockResolvedValue(share);
  vi.mocked(threadSharesApi.preview)
    .mockResolvedValueOnce(preview)
    .mockResolvedValue({
      ...preview,
      preview_digest: "new-digest",
      messages: [{ id: 1, role: "user", content: "Newly reviewed text" }],
    });
  render(
    <MemoryRouter>
      <ShareManagementDialog
        agentId="expert"
        threadId="thread"
        onClose={noop}
      />
    </MemoryRouter>,
  );
  await screen.findByText("Public question");
  await user.click(screen.getByRole("button", { name: "chatShare.create" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "chatShare.errors.stale",
  );
  expect(
    screen.getByRole("button", { name: "chatShare.create" }),
  ).toBeDisabled();
  expect(screen.queryByText("Public question")).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "chatShare.refreshPreview" }),
  );
  await screen.findByText("Newly reviewed text");
  fireEvent.mouseDown(screen.getByRole("combobox"));
  await user.click(await screen.findByText("chatShare.never"));
  await user.click(screen.getByRole("button", { name: "chatShare.create" }));
  expect(threadSharesApi.create).toHaveBeenLastCalledWith(
    "expert",
    "thread",
    "new-digest",
    null,
  );
});

it("shows origin-required errors without building a URL from the browser host", async () => {
  vi.mocked(threadSharesApi.create).mockRejectedValue(
    new Error(
      '503 - {"error":{"code":"SHARE_ORIGIN_REQUIRED","message":"SECRET private settings"}}',
    ),
  );
  render(
    <MemoryRouter>
      <ShareManagementDialog
        agentId="expert"
        threadId="thread"
        onClose={noop}
      />
    </MemoryRouter>,
  );
  await screen.findByText("Public question");
  fireEvent.click(screen.getByRole("button", { name: "chatShare.create" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "chatShare.errors.originRequired",
  );
  expect(screen.queryByText(/SECRET/)).not.toBeInTheDocument();
  expect(
    screen.queryByRole("textbox", { name: "chatShare.url" }),
  ).not.toBeInTheDocument();
});

it("lists centrally from a normal settings entry, pages by exclusive cursor and closes any active owner link", async () => {
  const expired = {
    ...share,
    share_id: "expired",
    title: "Expired snapshot",
    status: "expired" as const,
    public_url: null,
  };
  vi.mocked(threadSharesApi.list)
    .mockResolvedValueOnce({
      shares: [share],
      next_before: "40",
      has_more: true,
    })
    .mockResolvedValueOnce({
      shares: [expired],
      next_before: null,
      has_more: false,
    });
  const settings = buildNavSections(null).find(
    (section) => section.id === "settings",
  );
  expect(
    settings?.items.find((item) => item.key === "thread-shares")?.path,
  ).toBe("/settings/thread-shares");
  render(<ThreadSharesPage />);
  expect(
    screen.getAllByRole("heading", { name: "chatShare.allLinks" }),
  ).toHaveLength(1);
  expect(
    screen.getByRole("region", { name: "chatShare.links" }),
  ).toBeInTheDocument();
  await screen.findByDisplayValue(share.public_url!);
  fireEvent.click(screen.getByRole("button", { name: "chatShare.more" }));
  expect(await screen.findByText("Expired snapshot")).toBeInTheDocument();
  expect(threadSharesApi.list).toHaveBeenLastCalledWith(undefined, "40");
  expect(
    screen.getAllByRole("button", { name: "chatShare.copy" }),
  ).toHaveLength(1);
  fireEvent.click(
    screen.getAllByRole("button", { name: "chatShare.close" })[0],
  );
  await screen.findByText("chatShare.closed");
  expect(
    screen.queryByRole("button", { name: "chatShare.copy" }),
  ).not.toBeInTheDocument();
});

it("reaches the same sharing dialog through the mobile historical session menu", async () => {
  const user = userEvent.setup();
  function MobileJourney() {
    const [scope, setScope] = useState<{
      agentId: string;
      threadId: string;
    } | null>(null);
    return (
      <>
        <ChatSidebarPanel
          isMobile
          sidebarOpen
          sidebarWidth={250}
          agents={[
            {
              agent_id: "expert",
              name: "Expert",
              state: "running",
            } as OctopAgent,
          ]}
          sessions={[session]}
          activeThreadId="thread"
          resolvedAgentId="expert"
          sessionsHasMore={false}
          sessionsLoadingMore={false}
          onLoadMoreSessions={noop}
          onFetchAllSessions={noop}
          onSelectSession={noop}
          onAgentSelect={noop}
          onNewChatWithAgent={noop}
          onDeleteSession={noop}
          onRenameSession={noop}
          onPinSession={noop}
          onForkSession={noop}
          onShareSession={(id, agent) =>
            setScope({ agentId: agent!, threadId: id })
          }
          onSidebarOpenChange={noop}
          onSidebarResizeStart={noop}
        />
        {scope && (
          <ShareManagementDialog {...scope} onClose={() => setScope(null)} />
        )}
      </>
    );
  }
  render(
    <MemoryRouter>
      <MobileJourney />
    </MemoryRouter>,
  );
  await user.click(
    screen.getByRole("button", { name: /更多|common.more|More/ }),
  );
  await user.click(
    await screen.findByRole("menuitem", { name: "chatShare.title" }),
  );
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  await screen.findByText("Public question");
  expect(threadSharesApi.preview).toHaveBeenCalledWith("expert", "thread");
});

it("renders markdown without image loads, raw HTML, private/relative links or shell actions", async () => {
  render(
    <PublicMarkdown
      content={
        '# Heading\n\n![tracking](https://tracker.invalid/image.png)\n\n<img src="https://tracker.invalid/raw">\n\n[public](https://example.org/paper) [relative](/api/secret) [private](http://localhost:3000/api/private) [script](javascript:alert(1))\n\n```bash\nrm private\n```'
      }
    />,
  );
  expect(
    await screen.findByRole("heading", { name: "Heading" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.getAllByRole("link")).toHaveLength(1);
  expect(screen.getByRole("link")).toHaveAttribute(
    "rel",
    "noreferrer noopener",
  );
  expect(screen.getByRole("link")).toHaveAttribute(
    "referrerpolicy",
    "no-referrer",
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(screen.getByText("rm private")).toBeInTheDocument();
});

it.each([
  "http://localhost:9999/report",
  "http://127.0.0.1:8188/report",
  "http://2130706433/report",
  "http://10.0.0.5/report",
  "http://172.16.0.5/report",
  "http://192.168.1.5/report",
  "http://169.254.169.254/latest/meta-data",
  "http://[::1]/report",
  "http://[fd00::1]/report",
  "http://[fe80::1]/report",
  "http://[::ffff:192.168.1.5]/report",
  "https://private.example/api/private",
  "https://private.example/%61pi/private",
  "https://private.example/share/other-capability",
])("blocks cross-origin private manual and GFM links: %s", (url) => {
  render(
    <PublicMarkdown
      content={`[private](${url})\n\n<${url}>\n\n${url}\n\n[public](https://example.org/paper)`}
    />,
  );
  expect(screen.getAllByRole("link")).toHaveLength(1);
  expect(screen.getByRole("link")).toHaveAttribute(
    "href",
    "https://example.org/paper",
  );
});

it("keeps all sharing copy bilingual", () => {
  const keys = (data: Record<string, unknown>): string[] =>
    Object.entries(data)
      .flatMap(([key, value]) =>
        typeof value === "object" && value
          ? keys(value as Record<string, unknown>).map(
              (child) => `${key}.${child}`,
            )
          : key,
      )
      .sort();
  expect(keys(en.chatShare)).toEqual(keys(zh.chatShare));
});
