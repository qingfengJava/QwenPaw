/**
 * DirBrowser — in-app server directory browser built on the console
 * browse-dirs API (`fsApi.browseDirs`). Shared by the workspace dialogs
 * and the open-folder fallback modal.
 *
 * Starts at the home directory ("~"; on Windows "/" lists drive letters),
 * navigates with single clicks and confirms the current directory via the
 * footer button.
 */
import { useCallback, useEffect, useState } from "react";
import { fsApi } from "../../api/modules";
import type { BrowseDirsResult } from "../../api/modules";

export interface DirBrowserProps {
  /** Server-side starting point ("~" by default; "/" = Windows drives). */
  initialPath?: string;
  /** Fired when the user confirms the current directory. */
  onSelect: (path: string) => void;
  /** Footer confirm label (some parents phrase it differently). */
  confirmLabel?: string;
}

export default function DirBrowser({
  initialPath = "~",
  onSelect,
  confirmLabel = "使用当前目录",
}: DirBrowserProps) {
  const [state, setState] = useState<BrowseDirsResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (path: string) => {
    setLoading(true);
    setError(null);
    try {
      setState(await fsApi.browseDirs(path));
    } catch (err) {
      setState(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(initialPath);
    // Re-seed only when the browser remounts with a new start point.
  }, [initialPath, load]);

  return (
    <div className="dir-browser">
      <div className="dir-browser-path">
        <i className="fa-regular fa-folder-open" />
        <span className="dir-browser-current" title={state?.current ?? ""}>
          {state?.current ?? (loading ? "加载中…" : "—")}
        </span>
        <button
          type="button"
          className="icon-btn"
          aria-label="刷新"
          disabled={!state || loading}
          onClick={() => state && void load(state.current)}
        >
          <i className="fa-solid fa-rotate-right" />
        </button>
      </div>

      {error && (
        <div className="dir-browser-error">
          <span>{error}</span>
          <button type="button" className="btn-plain" onClick={() => void load(initialPath)}>
            重试
          </button>
        </div>
      )}

      {!error && (
        <ul className="dir-browser-list">
          {state?.parent && (
            <li>
              <button
                type="button"
                className="dir-browser-item dir-browser-parent"
                onClick={() => void load(state.parent as string)}
              >
                <i className="fa-solid fa-arrow-up" />
                <span>{state.parent === "/" ? "上级（此电脑 / 盘符）" : "上级目录"}</span>
              </button>
            </li>
          )}
          {state?.dirs.map((dir) => (
            <li key={dir.path}>
              <button
                type="button"
                className="dir-browser-item"
                title={dir.path}
                onClick={() => void load(dir.path)}
              >
                <i className="fa-regular fa-folder" />
                <span>{dir.name}</span>
              </button>
            </li>
          ))}
          {!loading && state && state.dirs.length === 0 && (
            <li className="dir-browser-empty">此目录下没有子目录</li>
          )}
          {loading && <li className="dir-browser-empty">加载中…</li>}
        </ul>
      )}

      <div className="dir-browser-footer">
        <button
          type="button"
          className="btn-black"
          disabled={!state || loading || !!error}
          onClick={() => state && onSelect(state.current)}
        >
          <i className="fa-solid fa-check" />
          {confirmLabel}
        </button>
      </div>
    </div>
  );
}
