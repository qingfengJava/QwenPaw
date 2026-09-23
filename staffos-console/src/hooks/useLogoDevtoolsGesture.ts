/**
 * useLogoDevtoolsGesture — 品牌标 3 秒内连击 8 次打开 DevTools（仅 Tauri 桌面壳）。
 *
 * 隐藏支持入口：桌面壳不提供默认右键菜单/快捷键开 DevTools 的通道，保留一个
 * 不易误触的手势给支持/调试用。logo 从顶栏迁到侧栏顶部后，手势跟随品牌标，
 * 供 Sidebar 的 logo 点击调用。
 *
 * @author qingfeng
 */
import { useRef } from "react";
import { message } from "antd";
import { invoke } from "@tauri-apps/api/core";
import { isDesktopApp } from "../tauri/backendRuntime";

export function useLogoDevtoolsGesture() {
  const logoClicksRef = useRef<number[]>([]);

  return () => {
    if (!isDesktopApp()) return;
    const now = Date.now();
    const windowStart = now - 3000;
    logoClicksRef.current = logoClicksRef.current.filter(
      (time) => time > windowStart,
    );
    logoClicksRef.current.push(now);
    if (logoClicksRef.current.length >= 8) {
      logoClicksRef.current = [];
      invoke("open_devtools")
        .then(() => message.success("DevTools opened"))
        .catch((err: unknown) => {
          const errMsg =
            err instanceof Error
              ? err.message
              : typeof err === "string"
              ? err
              : JSON.stringify(err);
          console.error("Failed to open DevTools:", errMsg);
          message.error(`DevTools error: ${errMsg}`);
        });
    }
  };
}
