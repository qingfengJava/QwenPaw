/**
 * reorder.ts — 控制台卡片「上移/下移」的全量重排计算（纯函数）。
 *
 * 后端 PUT /agents/order 要求提交的 id 清单与 configured profiles
 * 全量相等（各出现一次），且保持「default 第一 → 置顶 → 普通」分组；
 * 因此换位必须以全量列表为基准，筛选视图只用来定位移动目标的邻居
 * （否则任意筛选/分 Tab 下提交子集必然 400）。
 *
 * @author qingfeng
 */
import type { DigitalEmployee } from "@/api/modules/employeeRegistry";

export interface ReorderResult {
  /** false = 无法换位（越界/找不到行），调用方静默忽略。 */
  ok: boolean;
  /** true = 换位会破坏 default/置顶分组约束，调用方应提示而非提交。 */
  violatesGrouping: boolean;
  /** 全量 id 清单（已换位）；ok=false 时为空数组。 */
  ids: string[];
}

/** 只允许已物化为运行时 agent 的行参与排序（草稿员工无 profile）。 */
function eligible(row: DigitalEmployee): boolean {
  return Boolean(row.startup_status);
}

/** 后端 ``_is_valid_display_order`` 的前端同源复刻（防 400 于未然）。 */
export function respectsAgentGrouping(
  rows: DigitalEmployee[],
  ids: string[],
): boolean {
  const pinnedById = new Map(rows.map((row) => [row.agent_id, row.pinned]));
  let seenUnpinned = false;
  for (const id of ids) {
    if (id === "default") {
      // default agent 必须居首，出现在其他任何位置即违规
      if (ids[0] !== id) {
        return false;
      }
      continue;
    }
    if (pinnedById.get(id)) {
      if (seenUnpinned) {
        return false;
      }
    } else {
      seenUnpinned = true;
    }
  }
  return true;
}

export function computeReorder(
  allRows: DigitalEmployee[],
  visibleRows: DigitalEmployee[],
  employee: DigitalEmployee,
  offset: -1 | 1,
): ReorderResult {
  const orderedAll = allRows.filter(eligible);
  const orderedVisible = visibleRows.filter(eligible);
  const fromVisible = orderedVisible.findIndex(
    (row) => row.agent_id === employee.agent_id,
  );
  const targetVisible = fromVisible + offset;
  if (
    fromVisible < 0 ||
    targetVisible < 0 ||
    targetVisible >= orderedVisible.length
  ) {
    return { ok: false, violatesGrouping: false, ids: [] };
  }
  const from = orderedAll.findIndex(
    (row) => row.agent_id === employee.agent_id,
  );
  const to = orderedAll.findIndex(
    (row) => row.agent_id === orderedVisible[targetVisible].agent_id,
  );
  if (from < 0 || to < 0) {
    return { ok: false, violatesGrouping: false, ids: [] };
  }
  const ids = orderedAll.map((row) => row.agent_id);
  [ids[from], ids[to]] = [ids[to], ids[from]];
  return {
    ok: true,
    violatesGrouping: !respectsAgentGrouping(allRows, ids),
    ids,
  };
}
