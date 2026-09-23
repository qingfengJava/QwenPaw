/**
 * DirBrowser — in-app server directory browser built on the console
 * browse-dirs API (`fsApi.browseDirs`). Shared by the workspace dialogs
 * and the open-folder fallback modal.
 *
 * Navigation affordances (fallback for deployments without the native
 * OS picker): a one-click drive strip (C:/D:/… fetched from the virtual
 * "/" root — no more step-by-step climbing to switch drives) plus
 * clickable breadcrumbs for the current path. Starts at the home
 * directory; confirms via the footer button.
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

interface Crumb {
  label: string;
  path: string;
}

const DRIVE_RE = /^[A-Za-z]:$/;

/** Split an absolute path into clickable crumbs (Windows + POSIX). */
function breadcrumbsOf(current: string): Crumb[] {
  if (current === "/" || current === "\\") {
    return [{ label: "此电脑（盘符）", path: "/" }];
  }
  const norm = current.replace(/\//g, "\\");
  const match = /^([A-Za-z]:)(.*)$/.exec(norm);
  if (match) {
    const drive = `${match[1]}\\`;
    const crumbs: Crumb[] = [{ label: match[1], path: drive }];
    let acc = drive;
    for (const part of match[2].split("\\").filter(Boolean)) {
      acc = `${acc}${part}`;
      crumbs.push({ label: part, path: acc });
      acc = `${acc}\\`;
    }
    return crumbs;
  }
  // POSIX absolute path
  const crumbs: Crumb[] = [{ label: "/", path: "/" }];
  let acc = "";
  for (const part of norm.split("\\").filter(Boolean)) {
    acc = `${acc}/${part}`;
    crumbs.push({ label: part, path: acc });
  }
  return crumbs;
}

export default function DirBrowser({
  initialPath = "~",
  onSelect,
  confirmLabel = "使用当前目录",
}: DirBrowserProps) {
  const [state, setState] = useState<BrowseDirsResult | null>(null);
  const [drives, setDrives] = useState<{ name: string; path: string }[]>([]);
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

  // One-time drive strip fetch (virtual "/" root lists drives on Windows;
  // entries not shaped like "D:" are ignored so POSIX roots stay clean).
  useEffect(() => {
    let cancelled = false;
    fsApi
      .browseDirs("/")
      .then((r) => {
        if (!cancelled) {
          setDrives(r.dirs.filter((d) => DRIVE_RE.test(d.name)));
        }
      })
      .catch(() => {
        /* drive strip is a convenience — silent fallback */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    void load(initialPath);
    // Re-seed only when the browser remounts with a new start point.
  }, [initialPath, load]);

  const crumbs = state ? breadcrumbsOf(state.current) : [];

  return (
    <div className="dir-browser">
      {drives.length > 0 && (
        <div className="dir-browser-drives">
          {drives.map((d) => (
            <button
              key={d.path}
              type="button"
              className="dir-browser-drive-chip"
              title={d.path}
              onClick={() => void load(d.path)}
            >
              {d.name}
            </button>
          ))}
        </div>
      )}

      <div className="dir-browser-path">
        <i className="fa-regular fa-folder-open" />
        <span className="dir-browser-current" title={state?.current ?? ""}>
          {crumbs.length > 0 ? (
            crumbs.map((c, i) => (
              <span key={c.path} className="dir-browser-crumb-wrap">
                {i > 0 && <i className="fa-solid fa-chevron-right dir-browser-crumb-sep" />}
                <button
                  type="button"
                  className="dir-browser-crumb"
                  disabled={loading || c.path === state?.current}
                  onClick={() => void load(c.path)}
                >
                  {c.label}
                </button>
              </span>
            ))
          ) : loading ? (
            "加载中…"
          ) : (
            "—"
          )}
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
                <span>上级目录</span>
              </button>
            </li>
          )}
          {state?.dirs
            .filter((dir) => !DRIVE_RE.test(dir.name) || state.current !== "/")
            .map((dir) => (
              <li key={dir.path}>
                <button
                  type="button"
                  className="dir-browser-item"
                  title={dir.path}
                  onClick={() => void load(dir.path)}
                >
                  <i
                    className={
                      DRIVE_RE.test(dir.name)
                        ? "fa-solid fa-hard-drive"
                        : "fa-regular fa-folder"
                    }
                  />
                  <span>{dir.name}</span>
                </button>
              </li>
            ))}
          {!loading && state && state.dirs.length === 0 && (
            <li className="dir-browser-empty">
              {state.current === "/"
                ? "点击上方盘符进入对应磁盘"
                : "此目录下没有子目录"}
            </li>
          )}
          {loading && <li className="dir-browser-empty">加载中…</li>}
        </ul>
      )}

      <div className="dir-browser-footer">
        <button
          type="button"
          className="btn-black"
          disabled={!state || loading || !!error || state.current === "/"}
          onClick={() => state && onSelect(state.current)}
        >
          <i className="fa-solid fa-check" />
          {confirmLabel}
        </button>
      </div>
    </div>
  );
}
