/**
 * pageTitleRegistry.ts — 详情页运行时标题的内存注册表。
 *
 * 详情页（员工详情 / 内嵌应用）的标签名来自接口数据，菜单树里查不到。页面拿到
 * 实体名后写入本表，标签栏与面包屑按归一化 key 读取；未写入时回退 routeNavMeta
 * 声明的兜底文案，保证不出现空白标签。
 *
 * 刻意不进 localStorage：标题会随数据变化（员工改名），落库会让标签长期挂着旧名字。
 *
 * @author qingfeng
 */

/** key → 标题。Map 保持插入序，超限时按最早写入淘汰。 */
const titles = new Map<string, string>();

/** 容量上限：同时打开的标签远小于此值，仅防泄漏。 */
const MAX_ENTRIES = 50;

type Listener = () => void;
const listeners = new Set<Listener>();

/** 每次写入递增，供 useSyncExternalStore 作为廉价快照。 */
let version = 0;

function emit(): void {
  version += 1;
  listeners.forEach((listener) => listener());
}

/** 当前快照版本（引用值，可直接做 useSyncExternalStore 的 getSnapshot）。 */
export function getPageTitleVersion(): number {
  return version;
}

/** 写入（或覆盖）某个标签 key 的标题。空串视为无效写入，直接忽略。 */
export function setPageTitle(key: string, title: string): void {
  if (!key || !title) return;
  const previous = titles.get(key);
  if (previous === title) return;

  // 覆盖写入时先删再设，让 Map 的插入序始终反映最近写入，淘汰策略才是 FIFO。
  titles.delete(key);
  titles.set(key, title);

  if (titles.size > MAX_ENTRIES) {
    const oldest = titles.keys().next().value;
    if (oldest !== undefined) titles.delete(oldest);
  }
  emit();
}

/** 读取标题，未回填时返回 undefined。 */
export function getPageTitle(key: string): string | undefined {
  return titles.get(key);
}

/** 订阅变更（供 useSyncExternalStore 使用）。 */
export function subscribePageTitle(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** 测试用：清空全部标题与订阅。 */
export function __resetPageTitlesForTests(): void {
  titles.clear();
  listeners.clear();
}
