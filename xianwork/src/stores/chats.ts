/**
 * chats store — the single source of truth for the sidebar chat tree
 * (task group + workspace groups), replacing the duplicated
 * chatApi.list fetches in MainLayout and Chat.tsx. All mutating
 * sidebar actions (rename / remove / batch ops / bind / unbind) flow
 * through here and end with one reload, so every surface stays
 * consistent without per-component refetching.
 *
 * Grouping itself is server-side: GET /xian/workspaces?include_chats=true
 * matches each chat's meta.runtime_context.project_dir against the
 * registered dir_path (normalized + case-folded), so this store never
 * compares paths on the client.
 */
import { useMemo } from "react";
import { create } from "zustand";
import { chatApi, workspaceApi } from "../api/modules";
import type { ChatSpecView, WorkspaceView } from "../api/modules";

/** Monotonic sequence: a stale in-flight reload is discarded. */
let reloadSeq = 0;

interface ChatsState {
  /** Workspace groups, each with nested chats (include_chats=true). */
  workspaces: WorkspaceView[];
  /** Active chats not bound to any workspace (task group, newest first). */
  unboundChats: ChatSpecView[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  /** Mutations below all end with reload() — single invalidation point. */
  renameChat: (chatId: string, name: string) => Promise<void>;
  /** Pin/unpin via PUT /chats/{id} (ChatUpdate.pinned). */
  togglePin: (chatId: string, pinned: boolean) => Promise<void>;
  removeChat: (chatId: string) => Promise<void>;
  batchRemove: (chatIds: string[]) => Promise<void>;
  /** Single-chat archive on top of the batch endpoint; returns its detail. */
  archiveChat: (
    chatId: string,
  ) => Promise<{
    succeeded: string[];
    failed: { chat_id: string; reason: string }[];
  }>;
  /** Returns the backend {succeeded, failed} detail for caller toasts. */
  batchArchive: (
    chatIds: string[],
  ) => Promise<{
    succeeded: string[];
    failed: { chat_id: string; reason: string }[];
  }>;
  bindChats: (workspaceId: string, chatIds: string[]) => Promise<void>;
  unbindChat: (workspaceId: string, chatId: string) => Promise<void>;
}

export const useChatsStore = create<ChatsState>()((set, get) => ({
  workspaces: [],
  unboundChats: [],
  loading: false,
  error: null,

  reload: async () => {
    const seq = ++reloadSeq;
    set({ loading: true, error: null });
    try {
      const result = await workspaceApi.list(true);
      if (seq !== reloadSeq) return; // superseded by a newer reload
      set({
        workspaces: result.workspaces,
        unboundChats: result.unbound_chats,
        loading: false,
      });
    } catch (err) {
      if (seq !== reloadSeq) return;
      set({
        error: err instanceof Error ? err.message : String(err),
        loading: false,
      });
    }
  },

  renameChat: async (chatId, name) => {
    await chatApi.rename(chatId, name);
    await get().reload();
  },

  togglePin: async (chatId, pinned) => {
    await chatApi.togglePin(chatId, pinned);
    await get().reload();
  },

  removeChat: async (chatId) => {
    await chatApi.remove(chatId);
    await get().reload();
  },

  archiveChat: async (chatId) => {
    const result = await chatApi.batchArchive([chatId]);
    await get().reload();
    return result;
  },

  batchRemove: async (chatIds) => {
    await chatApi.batchRemove(chatIds);
    await get().reload();
  },

  batchArchive: async (chatIds) => {
    const result = await chatApi.batchArchive(chatIds);
    await get().reload();
    return result;
  },

  bindChats: async (workspaceId, chatIds) => {
    await workspaceApi.bindChats(workspaceId, chatIds);
    await get().reload();
  },

  unbindChat: async (workspaceId, chatId) => {
    await workspaceApi.unbindChat(workspaceId, chatId);
    await get().reload();
  },
}));

/** Flat, newest-first view of every visible chat (task + workspace groups). */
export function useAllChats(): ChatSpecView[] {
  const unboundChats = useChatsStore((s) => s.unboundChats);
  const workspaces = useChatsStore((s) => s.workspaces);
  return useMemo(
    () =>
      [...unboundChats, ...workspaces.flatMap((w) => w.chats ?? [])].sort(
        (a, b) =>
          (new Date(b.updated_at ?? 0).getTime() || 0) -
          (new Date(a.updated_at ?? 0).getTime() || 0),
      ),
    [unboundChats, workspaces],
  );
}
