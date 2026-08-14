/**
 * Login — username/password against the backend auth endpoint. When
 * auth is disabled the page offers a one-click local entry.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Input, message } from "antd";
import { authApi } from "../api/modules";
import { useAuthStore } from "../stores/auth";

export default function LoginPage() {
  const navigate = useNavigate();
  const signIn = useAuthStore((s) => s.signIn);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
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
      message.warning("请输入用户名和密码");
      return;
    }
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
        message.error("登录失败：服务端未返回 token");
        return;
      }
      signIn(token, username);
      navigate("/", { replace: true });
    } catch (err) {
      message.error(`登录失败：${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--bg-sidebar, #f7f7f8)",
      }}
    >
      <div
        style={{
          width: 380,
          background: "#fff",
          border: "1px solid var(--border-light, #eaeaec)",
          borderRadius: 16,
          padding: "36px 32px",
          boxShadow: "0 10px 30px rgba(0,0,0,0.06)",
        }}
      >
        <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>
          XianWork
        </div>
        <div
          style={{
            color: "var(--text-muted, #8e8e96)",
            marginBottom: 28,
            fontSize: 13,
          }}
        >
          企业智能工作台 · 登录
        </div>
        {authEnabled === false ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div
              style={{
                color: "var(--text-muted, #8e8e96)",
                fontSize: 13,
                lineHeight: 1.7,
              }}
            >
              服务端未开启认证（本机模式），无需账号密码，点击直接进入。
            </div>
            <Button
              type="primary"
              size="large"
              block
              onClick={enterLocally}
            >
              直接进入
            </Button>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Input
              size="large"
              placeholder="用户名"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              onPressEnter={handleLogin}
            />
            <Input.Password
              size="large"
              placeholder="密码"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onPressEnter={handleLogin}
            />
            <Button
              type="primary"
              size="large"
              block
              loading={busy}
              onClick={handleLogin}
            >
              登录
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
