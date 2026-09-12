import { useSearchParams } from "react-router-dom";
import { MarketplaceHeader } from "./components/MarketplaceHeader";
import AppCenterPage from "../AppCenter";
import PluginManagerPage from "../Settings/PluginManager";
import { InstallQueuePanel, MarketPanel } from "../Settings/Market/MarketPanel";
import {
  useMarketInstall,
  type InstallTarget,
  type MarketInstallController,
} from "../Settings/Market/useMarketInstall";
import { useAgentStore } from "../../stores/agentStore";
import styles from "./index.module.less";

/**
 * 安装目标解析：仅显式 ?target=workspace 才装进智能体工作区，
 * 其余（无参数 / pool）一律进共享技能池。市场作为公共入口，
 * 默认必须落到池，避免技能隐式绑死在当前选中智能体上（装完
 * 技能池看不到、二次安装报 already exists）。
 */
function getSkillMarketTarget(value: string | null): InstallTarget {
  return value === "workspace" ? "workspace" : "pool";
}

function SkillMarketplace({
  installTarget,
  install,
}: {
  installTarget: InstallTarget;
  install: MarketInstallController;
}) {
  return (
    <div className={styles.page}>
      <MarketplaceHeader activeSection="skills" />
      <MarketPanel installTarget={installTarget} install={install} />
    </div>
  );
}

export default function MarketplacePage() {
  const [searchParams] = useSearchParams();
  const tab = searchParams.get("tab");
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  // 员工技能页入口带 deliver=<agentId>：安装入池后立即分发给该员工
  const deliverAgentId = searchParams.get("deliver") || undefined;
  const install = useMarketInstall({ selectedAgent, deliverAgentId });

  let content = <AppCenterPage />;
  if (tab === "plugins") {
    content = <PluginManagerPage />;
  } else if (tab === "skills") {
    content = (
      <SkillMarketplace
        installTarget={getSkillMarketTarget(searchParams.get("target"))}
        install={install}
      />
    );
  }

  return (
    <>
      {content}
      {install.queue.length > 0 && (
        <InstallQueuePanel
          queue={install.queue}
          onClearCompleted={install.clearFinished}
          onCancel={install.cancel}
          onRetry={install.retry}
        />
      )}
    </>
  );
}
