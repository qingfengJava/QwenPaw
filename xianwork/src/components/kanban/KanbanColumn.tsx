/**
 * KanbanColumn — prototype L787-825: 280px #f8fafc column with header
 * (status dot + label + count + actions) and dashed empty state.
 * Accepts dragged TaskCards from other columns.
 */
import { useState } from "react";
import type { Task } from "../../api/modules";
import TaskCard, { COLUMN_META } from "./TaskCard";

export interface KanbanColumnProps {
  status: Task["status"];
  tasks: Task[];
  canEdit: boolean;
  onDropTask: (taskId: string, status: Task["status"]) => void;
  onAdd?: (status: Task["status"]) => void;
}

export default function KanbanColumn({
  status,
  tasks,
  canEdit,
  onDropTask,
  onAdd,
}: KanbanColumnProps) {
  const [dragOver, setDragOver] = useState(false);
  const meta = COLUMN_META[status];

  return (
    <div
      className={`kanban-column${dragOver ? " drag-over" : ""}`}
      onDragOver={(e) => {
        if (!canEdit) {
          return;
        }
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        if (!canEdit) {
          return;
        }
        const taskId = e.dataTransfer.getData("text/plain");
        if (taskId) {
          onDropTask(taskId, status);
        }
      }}
    >
      <div className="column-header">
        <div className="header-title">
          <div className={`status-dot ${meta.dot}`} />
          <span>{meta.label}</span>
          <span className="count">{tasks.length}</span>
        </div>
        <div className="column-actions">
          <i className="fa-solid fa-ellipsis" title="更多" />
          {canEdit && onAdd && (
            <i
              className="fa-solid fa-plus"
              title="添加事项"
              onClick={() => onAdd(status)}
            />
          )}
        </div>
      </div>

      {tasks.map((task) => (
        <TaskCard key={task.id} task={task} />
      ))}

      {tasks.length === 0 && <div className="empty-state">暂无事项</div>}
    </div>
  );
}
