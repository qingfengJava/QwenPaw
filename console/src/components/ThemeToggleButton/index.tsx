import { Dropdown, Button, type MenuProps } from "antd";
import { SparkMoonLine, SparkSunLine } from "@agentscope-ai/icons";
import { SunMoon } from "lucide-react";
import { useTheme, type ThemeMode } from "../../contexts/ThemeContext";
import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";
import styles from "./index.module.less";

const ICONS: Record<ThemeMode, ReactNode> = {
  light: <SparkSunLine />,
  dark: <SparkMoonLine />,
  system: <SunMoon size="1em" />,
};

export default function ThemeToggleButton() {
  const { themeMode, isDark, setThemeMode } = useTheme();
  const { t } = useTranslation();

  const items: MenuProps["items"] = [
    {
      key: "light",
      label: t("theme.light"),
      onClick: () => setThemeMode("light"),
    },
    {
      key: "dark",
      label: t("theme.dark"),
      onClick: () => setThemeMode("dark"),
    },
    {
      key: "system",
      label: t("theme.system"),
      onClick: () => setThemeMode("system"),
    },
  ];

  const icon =
    themeMode === "system" ? ICONS.system : ICONS[isDark ? "dark" : "light"];

  return (
    <Dropdown
      menu={{ items, selectedKeys: [themeMode] }}
      placement="bottomRight"
      // Dropdown 在 antd 5.29 尚无 classNames API，仍用 overlayClassName；
      // 其透传 Tooltip 触发的弃用误报已在 main.tsx 统一过滤
      overlayClassName={styles.themeDropdown}
    >
      <Button className={styles.toggleBtn} type="text" icon={icon} />
    </Dropdown>
  );
}
