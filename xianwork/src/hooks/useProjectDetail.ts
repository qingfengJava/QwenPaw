/**
 * useProjectDetail — the data layer behind the ProjectDetail page.
 *
 * Preserved from the scaffold: the parallel load (now ten-way incl.
 * bindings/automations/resources), optimistic kanban moves, project-AI
 * SSE send, and expert binding. New: live feed via subscribeFeed
 * (Last-Event-ID resume) merged into newest-first feed state.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  automationApi,
  bindingApi,
  directoryApi,
  expertApi,
  projectApi,
  resourceApi,
  taskApi,
} from "../api/modules";
import type {
  ConnectorView,
  Expert,
  ExpertTeam,
  FeedEvent,
  Project,
  ProjectAutomation,
  ProjectBinding,
  ProjectMember,
  SkillView,
  Task,
} from "../api/modules";
import { buildAgentRequest, streamChat } from "../lib/stream";
import { applyEvent, userItem, type TimelineItem } from "../chat/protocol";
import { subscribeFeed } from "../lib/feedStream";
import type { FeedStreamHandle } from "../lib/feedStream";

export interface ProjectDetailData {
  project: Project | null;
  tasks: Task[];
  feed: FeedEvent[];
  members: ProjectMember[];
  experts: Expert[];
  teams: ExpertTeam[];
  bindings: ProjectBinding[];
  automations: ProjectAutomation[];
  connectors: ConnectorView[];
  skills: SkillView[];
}

export function useProjectDetail(
  projectId: string,
  onNotify: (kind: "error" | "success" | "info", text: string) => void,
) {
  const [data, setData] = useState<ProjectDetailData>({
    project: null,
    tasks: [],
    feed: [],
    members: [],
    experts: [],
    teams: [],
    bindings: [],
    automations: [],
    connectors: [],
    skills: [],
  });
  const [chats, setChats] = useState<
    { id: string; name: string; updated_at: string }[]
  >([]);
  const [aiReply, setAiReply] = useState("");
  const [streaming, setStreaming] = useState(false);
  const streamRef = useRef<FeedStreamHandle | null>(null);

  const load = useCallback(async () => {
    try {
      const [
        project,
        tasks,
        feed,
        members,
        experts,
        teams,
        bindings,
        automations,
        connectors,
        skills,
      ] = await Promise.all([
        projectApi.get(projectId),
        taskApi.list(projectId),
        projectApi.feed(projectId),
        projectApi.members(projectId),
        expertApi.list().catch(() => []),
        expertApi.listTeams().catch(() => []),
        bindingApi.list(projectId).catch(() => []),
        automationApi.list(projectId).catch(() => []),
        resourceApi.connectors().catch(() => []),
        resourceApi.skills().catch(() => []),
      ]);
      setData({
        project,
        tasks,
        feed,
        members,
        experts,
        teams,
        bindings,
        automations,
        connectors,
        skills,
      });
      projectApi
        .projectChats(projectId)
        .then(setChats)
        .catch(() => setChats([]));
    } catch (err) {
      onNotify("error", `加载项目失败：${String(err)}`);
    }
  }, [projectId, onNotify]);

  useEffect(() => {
    load();
  }, [load]);

  // Live feed: SSE with resume; merge new events newest-first, dedup by id.
  useEffect(() => {
    if (!data.project) {
      return;
    }
    streamRef.current?.close();
    const handle = subscribeFeed(projectId, {
      onEvent: (raw) => {
        try {
          const event = JSON.parse(raw) as FeedEvent;
          if (!event || !event.id) {
            return;
          }
          setData((prev) => {
            if (prev.feed.some((item) => item.id === event.id)) {
              return prev;
            }
            return { ...prev, feed: [event, ...prev.feed] };
          });
        } catch {
          /* keepalive comment */
        }
      },
    });
    streamRef.current = handle;
    return () => {
      handle.close();
      streamRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, data.project?.id]);

  const canEdit = useMemo(
    () =>
      data.project?.member_role === "owner" ||
      data.project?.member_role === "editor",
    [data.project],
  );

  const handleMove = useCallback(
    async (taskId: string, status: Task["status"]) => {
      if (!canEdit) {
        return;
      }
      // Optimistic move, then persist (integration-test locked semantics:
      // PATCH status; sort_order follows on the server).
      setData((prev) => ({
        ...prev,
        tasks: prev.tasks.map((t) =>
          t.id === taskId ? { ...t, status } : t,
        ),
      }));
      try {
        const updated = await taskApi.update(projectId, taskId, { status });
        setData((prev) => ({
          ...prev,
          tasks: prev.tasks.map((t) =>
            t.id === taskId ? updated : t,
          ),
        }));
      } catch (err) {
        onNotify("error", String(err));
        load();
      }
    },
    [canEdit, projectId, onNotify, load],
  );

  const handleBind = useCallback(
    async (value: string) => {
      const [kind, ref_id] = value.split(":");
      await projectApi.update(projectId, {
        ai_binding: { kind, ref_id } as Project["ai_binding"],
      });
      onNotify("success", "项目 AI 已绑定");
      load();
    },
    [projectId, onNotify, load],
  );

  const sendToProjectAI = useCallback(
    async (text: string) => {
      if (!text || streaming) {
        return;
      }
      setStreaming(true);
      setAiReply("");
      try {
        // Merge events with the shared console protocol reducer and surface
        // assistant text (the project plane emits the same event shapes).
        let timeline: TimelineItem[] = [userItem(text)];
        await streamChat(
          `/xian/projects/${projectId}/chat`,
          buildAgentRequest(text, "default"),
          (raw) => {
            timeline = applyEvent(timeline, raw);
            const reply = timeline
              .filter(
                (it): it is Extract<TimelineItem, { kind: "assistant" }> => it.kind === "assistant",
              )
              .map((it) => it.text)
              .join("\n\n");
            setAiReply(reply);
          },
        );
        load();
      } catch (err) {
        setAiReply(`（项目 AI 连接失败：${String(err)}）`);
      } finally {
        setStreaming(false);
      }
    },
    [projectId, streaming, load],
  );

  return {
    ...data,
    chats,
    aiReply,
    streaming,
    canEdit,
    reload: load,
    handleMove,
    handleBind,
    sendToProjectAI,
  };
}

export { directoryApi };
