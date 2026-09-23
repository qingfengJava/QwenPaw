import { lazy, createElement } from "react";
import type { ComponentType, LazyExoticComponent } from "react";
import { moduleRegistry } from "../plugins/moduleRegistry";

const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Derive the module-registry key from an import path, e.g.
 *   "../pages/Settings/Debug/index.tsx"  →  "Settings/Debug/index"
 *   "../../pages/Settings/Debug"         →  "Settings/Debug/index"
 */
function pathToModuleKey(importPath: string): string {
  const key = importPath.replace(/^.*\/pages\//, "").replace(/\.[^.]+$/, "");
  // Bare-directory imports are registered as "<Dir>/index" in registerHostModules
  return key.includes("/") && !/\/index$/.test(key) ? `${key}/index` : key;
}

// 泛型以 props 类型 P 为参数（而非组件类型）：避免 ComponentType<unknown>
// 的参数逆变拒绝 FC<Props>，同时不需要 any；最终由 React.lazy 自身的
// ComponentType<any> 约束承接，带 props 的页面组件也能走 retry 且
// props 类型完整保留。
function retryImport<T>(
  factory: () => Promise<{ default: T }>,
  retries: number,
): Promise<{ default: T }> {
  return factory().catch((error: unknown) => {
    if (retries <= 0) throw error;
    return new Promise<{ default: T }>((resolve) =>
      setTimeout(
        () => resolve(retryImport(factory, retries - 1)),
        RETRY_DELAY_MS,
      ),
    );
  });
}

// All page modules, keyed relative to this file (src/utils/).
// e.g. "../pages/Settings/Debug/index.tsx"
const PAGE_MODULES = import.meta.glob<ComponentType<unknown>>(
  ["../pages/**/*.{ts,tsx}", "!../pages/**/*.test.{ts,tsx}"],
  { import: "default" },
);

/**
 * Normalize any caller-relative path to the glob key used by PAGE_MODULES.
 * Callers in src/layouts/MainLayout use "../../pages/…"
 * The glob map is keyed as "../pages/…" (relative to src/utils/).
 */
function toGlobKey(path: string): string {
  // Strip everything up to and including the first occurrence of "pages/"
  let afterPages = path.replace(/^.*pages\//, "pages/");
  // Remove a bare "/index" suffix so both "Foo/index" and "Foo" resolve the same
  afterPages = afterPages.replace(/\/index$/, "");
  // Add the ../  prefix to match the glob map
  return `../${afterPages}`;
}

/**
 * 给懒加载组件挂一个 preload 钩子，供顶部标签栏 hover 时提前拉取分包。
 * 浏览器对同一 dynamic import 只会真正拉一次，重复调用返回同一 promise。
 */
export interface PreloadableComponent {
  preload?: () => void;
}

function withPreload<T>(component: T, factory: () => unknown): T {
  Object.defineProperty(component as object, "preload", {
    value: () => {
      try {
        (factory() as Promise<unknown> | undefined)?.catch?.(() => {
          // 预加载失败静默忽略：真正导航时 React.lazy 会走原有的重试与错误边界。
        });
      } catch {
        // 同上，预加载绝不允许影响交互。
      }
    },
    configurable: true,
    enumerable: false,
  });
  return component;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Like `React.lazy` but retries on chunk-load failure.
 * Pass the import path as a second argument to enable plugin-registry lookup:
 *
 * ```ts
 * // registry lookup enabled
 * const DebugPage = lazyWithRetry(
 *   () => import("../../pages/Settings/Debug"),
 *   "../../pages/Settings/Debug",
 * );
 * // no registry lookup (default behaviour, unchanged)
 * const ModelsPage = lazyWithRetry(() => import("../../pages/Settings/Models"));
 * ```
 */
export function lazyWithRetry<P>(
  factory: () => Promise<{ default: ComponentType<P> }>,
  moduleKeyOrPath?: string,
): LazyExoticComponent<ComponentType<P>> {
  return lazy(() =>
    retryImport(factory, MAX_RETRIES).then((mod) => {
      if (!moduleKeyOrPath) return mod;
      const key = moduleKeyOrPath.startsWith(".")
        ? pathToModuleKey(moduleKeyOrPath)
        : moduleKeyOrPath;
      const patched = moduleRegistry.get(key, "default");
      if (patched) return { default: patched as ComponentType<P> };
      return mod;
    }),
  );
}

/**
 * Convenience variant — call sites only need the **path string**.
 * The dynamic import is sourced from an `import.meta.glob` map, so Vite
 * still creates individual chunks while allowing a runtime registry override.
 *
 * Path is relative to the caller — bare-directory or full-extension paths both work:
 *
 * ```ts
 * // from src/layouts/MainLayout/ — bare directory, index.tsx resolved automatically
 * const DebugPage = lazyImportWithRetry("../../pages/Settings/Debug");
 * ```
 *
 * Any plugin that patches `Settings/Debug/index.default` in the module
 * registry will automatically take effect.
 */
export function lazyImportWithRetry(
  path: string,
): ReturnType<typeof lazy<ComponentType<unknown>>> {
  // Normalise to the glob-map key (relative to src/utils/).
  // Bare-directory paths like "../../pages/Settings/Debug" are tried with
  // /index.tsx and /index.ts suffixes automatically; extension-less file
  // paths like "../../pages/Agents/AgentsGalleryPage" are tried with
  // .tsx and .ts suffixes automatically.
  const base = toGlobKey(path);
  const globKey = PAGE_MODULES[base]
    ? base
    : PAGE_MODULES[`${base}.tsx`]
    ? `${base}.tsx`
    : PAGE_MODULES[`${base}.ts`]
    ? `${base}.ts`
    : PAGE_MODULES[`${base}/index.tsx`]
    ? `${base}/index.tsx`
    : PAGE_MODULES[`${base}/index.ts`]
    ? `${base}/index.ts`
    : base;
  const factory = PAGE_MODULES[globKey];
  if (!factory) {
    // Degrade to an error placeholder instead of throwing: this runs during
    // route-module evaluation, and a throw here blanks the entire app.
    // Typical cause: a new page file created while the dev server is running
    // (its glob map is stale until restart); prod builds never hit this.
    console.error(
      `[lazyImportWithRetry] No glob entry found for "${path}". ` +
        `Resolved key: "${globKey}". ` +
        `Available: ${Object.keys(PAGE_MODULES).length} entries.`,
    );
    const MissingPage = () =>
      createElement(
        "div",
        { style: { padding: 32, color: "rgba(0,0,0,0.45)" } },
        `Module not found: ${path} (dev server may need a restart)`,
      );
    return lazy(() =>
      Promise.resolve({
        default: MissingPage as unknown as ComponentType<unknown>,
      }),
    );
  }
  const key = pathToModuleKey(path);
  const component = lazy(() =>
    retryImport(
      () => factory().then((comp) => ({ default: comp })),
      MAX_RETRIES,
    ).then((mod) => {
      const patched = moduleRegistry.get(key, "default");
      if (patched) return { default: patched as ComponentType<unknown> };
      return mod;
    }),
  );
  // 标签栏 hover 预加载用（见 NavTabsBar）。
  return withPreload(component, () => factory());
}
