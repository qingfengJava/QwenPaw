/**
 * Login — extension page in the prototype design language: centred card
 * on the sidebar grey, accent-green primary button. Auth-disabled probe
 * and token flow preserved verbatim from the scaffold.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { authApi } from "../api/modules";
import { useAuthStore } from "../stores/auth";

export default function LoginPage() {
  const navigate = useNavigate();
  const signIn = useAuthStore((s) => s.signIn);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // null = probing; true/false = auth enabled/disabled on the backend.
  const [authEnabled, setAuthEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    authApi
      .status()
      .then((s) => {
        if (!cancelled) setAuthEnabled(Boolean(s.enabled));
      })
      .catch(() => {
        // Probe failed: assume enabled so the form stays the safe default.
        if (!cancelled) setAuthEnabled(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const enterLocally = () => {
    // Auth disabled on the backend: no token is required; every API is
    // open and the caller identity resolves to "local".
    signIn("local", "local");
    navigate("/", { replace: true });
  };

  const handleLogin = async () => {
    if (!username || !password) {
      setError("请输入用户名和密码");
      return;
    }
    setError("");
    setBusy(true);
    try {
      const res = await authApi.login(username, password);
      const token = (res as unknown as { token?: string }).token ?? "";
      if (!token) {
        // Empty token with auth disabled means "no credentials needed".
        if (authEnabled === false) {
          enterLocally();
          return;
        }
        setError("登录失败：服务端未返回 token");
        return;
      }
      signIn(token, username);
      navigate("/", { replace: true });
    } catch (err) {
      setError(`登录失败：${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-center">
      <div className="login-card">
        <div className="login-logo">XianWork</div>
        <div className="login-sub">企业智能工作台 · 登录</div>

        {authEnabled === false ? (
          <>
            <div
              style={{
                color: "var(--text-muted)",
                fontSize: 13,
                lineHeight: 1.7,
                marginBottom: 18,
                textAlign: "center",
              }}
            >
              服务端未开启认证（本机模式）
              <br />
              无需账号密码，点击直接进入
            </div>
            <button type="button" className="btn-accent" onClick={enterLocally}>
              直接进入
            </button>
          </>
        ) : (
          <>
            {error && <div className="login-error">{error}</div>}
            <div className="login-field">
              <label>用户名</label>
              <input
                autoComplete="username"
                placeholder="请输入用户名"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    void handleLogin();
                  }
                }}
              />
            </div>
            <div className="login-field">
              <label>密码</label>
              <input
                type="password"
                autoComplete="current-password"
                placeholder="请输入密码"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    void handleLogin();
                  }
                }}
              />
            </div>
            <button
              type="button"
              className="btn-accent"
              disabled={busy}
              onClick={() => void handleLogin()}
            >
              {busy ? "登录中…" : "登录"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
