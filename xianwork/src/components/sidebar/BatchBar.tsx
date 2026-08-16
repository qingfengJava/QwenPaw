/**
 * BatchBar — multi-select action strip for the sidebar (competitor shot 3).
 *
 * Select-all checkbox + live「全选 (n)」count, red 删除, 归档, and an
 * exit (×) that leaves batch mode. Running chats are excluded from the
 * selectable total by the caller.
 */
export interface BatchBarProps {
  selectedCount: number;
  selectableCount: number;
  allSelected: boolean;
  busy: boolean;
  onToggleAll: (checked: boolean) => void;
  onDelete: () => void;
  onArchive: () => void;
  onExit: () => void;
}

export default function BatchBar({
  selectedCount,
  selectableCount,
  allSelected,
  busy,
  onToggleAll,
  onDelete,
  onArchive,
  onExit,
}: BatchBarProps) {
  return (
    <div className="batch-bar">
      <label className="batch-bar-select-all">
        <input
          type="checkbox"
          checked={allSelected && selectableCount > 0}
          onChange={(e) => onToggleAll(e.target.checked)}
          disabled={selectableCount === 0 || busy}
          aria-label="全选"
        />
        <span>全选 ({selectedCount})</span>
      </label>
      <div className="batch-bar-actions">
        <button
          type="button"
          className="batch-btn batch-btn-archive"
          disabled={selectedCount === 0 || busy}
          onClick={onArchive}
        >
          归档
        </button>
        <button
          type="button"
          className="batch-btn batch-btn-delete"
          disabled={selectedCount === 0 || busy}
          onClick={onDelete}
        >
          删除
        </button>
        <button
          type="button"
          className="batch-btn batch-btn-exit"
          onClick={onExit}
          aria-label="退出批量操作"
        >
          <i className="fa-solid fa-xmark" />
        </button>
      </div>
    </div>
  );
}
