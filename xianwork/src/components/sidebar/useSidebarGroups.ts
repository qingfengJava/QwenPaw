/**
 * useSidebarGroups — derive the sidebar tree from the shared chats store.
 *
 * The server already groups and sorts (updated_at desc). The pure helper
 * below layers client-side ordering guarantees on top: pinned chats float
 * to the top of the task group and of every workspace group, then
 * newest-first; workspaces themselves stay newest-first so a stale list
 * never shuffles. Exported separately for unit tests without a React tree.
 */
import { useMemo } from "react";
import type { ChatSpecView, WorkspaceView } from "../../api/modules";
import { useChatsStore } from "../../stores/chats";

export interface SidebarGroups {
  unboundChats: ChatSpecView[];
  workspaces: WorkspaceView[];
}

/** pinned-first, then newest-first (never mutates the input). */
function byPinnedThenNewest(a: ChatSpecView, b: ChatSpecView): number {
  const pa = a.pinned ? 1 : 0;
  const pb = b.pinned ? 1 : 0;
  if (pa !== pb) {
    return pb - pa;
  }
  const ta = new Date(a.updated_at ?? 0).getTime() || 0;
  const tb = new Date(b.updated_at ?? 0).getTime() || 0;
  return tb - ta;
}

/** Pure derivation (testable): pinned-first chats, newest-first workspaces. */
export function deriveSidebarGroups(
  unboundChats: ChatSpecView[],
  workspaces: WorkspaceView[],
): SidebarGroups {
  const sortedWorkspaces = [...workspaces]
    .sort((a, b) => {
      const ta = new Date(a.updated_at ?? 0).getTime() || 0;
      const tb = new Date(b.updated_at ?? 0).getTime() || 0;
      return tb - ta;
    })
    .map((ws) =>
      ws.chats && ws.chats.length > 1
        ? { ...ws, chats: [...ws.chats].sort(byPinnedThenNewest) }
        : ws,
    );
  return {
    unboundChats: [...unboundChats].sort(byPinnedThenNewest),
    workspaces: sortedWorkspaces,
  };
}

export function useSidebarGroups(): SidebarGroups {
  const unboundChats = useChatsStore((s) => s.unboundChats);
  const workspaces = useChatsStore((s) => s.workspaces);
  return useMemo(
    () => deriveSidebarGroups(unboundChats, workspaces),
    [unboundChats, workspaces],
  );
}
