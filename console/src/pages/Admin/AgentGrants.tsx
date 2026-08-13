/**
 * Admin/AgentGrants — per-agent access control (M5, wraps M4-3 backend).
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { agentsApi } from "../../api/modules/agents";
import GrantPanel from "./GrantPanel";
import styles from "./admin.module.less";

function AgentGrantsPage() {
  const { t } = useTranslation();
  const [agentIds, setAgentIds] = useState<string[]>([]);

  useEffect(() => {
    agentsApi
      .listAgents()
      .then((res) => setAgentIds(res.agents.map((agent) => agent.id)))
      .catch(() => setAgentIds([]));
  }, []);

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("nav.adminAgentGrants", "Agent Access")}
      />
      <GrantPanel kind="agent" resourceOptions={agentIds} />
    </div>
  );
}

export default AgentGrantsPage;
