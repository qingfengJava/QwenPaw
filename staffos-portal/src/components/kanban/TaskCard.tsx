/**
 * TaskCard — prototype L829-886: title (strike-through when done),
 * task-status pill, time, assignee avatar. Draggable via HTML5 DnD;
 * the drop target lives on KanbanColumn.
 */
import Avatar, { pickColor } from "../Avatar";
import type { Task } from "../../api/modules";

export const COLUMN_META: Record<
  Task["status"],
  { label: string; dot: string }
> = {
  todo: { label: "待开始", dot: "dot-gray" },
  doing: { label: "进行中", dot: "dot-blue" },
  paused: { label: "已暂停", dot: "dot-orange" },
  done: { label: "已完成", dot: "dot-green" },
};

export interface TaskCardProps {
  task: Task;
  onDragStart?: (task: Task) => void;
  onDragEnd?: () => void;
}

function relativeTime(iso?: string | null): string {
  if (!iso) {
    return "";
  }
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) {
    return "";
  }
  const diff = Date.now() - then;
  const day = Math.floor(diff / 86_400_000);
  if (day <= 0) {
    return "今天";
  }
  if (day < 30) {
    return `${day}天前`;
  }
  const month = Math.floor(day / 30);
  if (month < 12) {
    return `${month}个月前`;
  }
  return `${Math.floor(month / 12)}年前`;
}

export default function TaskCard({ task, onDragStart, onDragEnd }: TaskCardProps) {
  const done = task.status === "done";
  const meta = COLUMN_META[task.status];
  return (
    <div
      className="task-card"
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", task.id);
        e.dataTransfer.effectAllowed = "move";
        onDragStart?.(task);
      }}
      onDragEnd={() => onDragEnd?.()}
    >
      <div className={`task-title${done ? " task-completed" : ""}`}>
        {task.title}
      </div>
      <div className="task-meta">
        <div className={`task-status${done ? " completed" : ""}`}>
          {done ? (
            <i className="fa-solid fa-check" />
          ) : (
            <div className={`status-dot ${meta.dot}`} />
          )}
          {meta.label}
          <span className="task-assignee-flag">
            {task.assignee ?? "无"}
          </span>
        </div>
        <div className="task-time">{relativeTime(task.updated_at ?? task.created_at)}</div>
      </div>
      <div className="task-card-footer">
        <Avatar
          name={task.assignee ?? task.creator}
          size={20}
          color={pickColor(task.assignee ?? task.creator)}
          className="task-assignee"
        />
      </div>
    </div>
  );
}
