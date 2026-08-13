/**
 * Admin/ModelGrants — per-model access control (M5, wraps M4-3 backend).
 *
 * Model keys follow the backend's `provider_id:model_name` convention
 * (see RetryChatModel.model_key); "*" matches every model.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { providerApi } from "../../api/modules/provider";
import GrantPanel from "./GrantPanel";
import styles from "./admin.module.less";

function ModelGrantsPage() {
  const { t } = useTranslation();
  const [modelKeys, setModelKeys] = useState<string[]>([]);

  useEffect(() => {
    providerApi
      .listProviders()
      .then((providers) => {
        const keys: string[] = [];
        for (const provider of providers) {
          const models = [...provider.models, ...provider.extra_models];
          for (const model of models) {
            keys.push(`${provider.id}:${model.id}`);
          }
        }
        setModelKeys(Array.from(new Set(keys)));
      })
      .catch(() => setModelKeys([]));
  }, []);

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("nav.adminModelGrants", "Model Access")}
      />
      <GrantPanel kind="model" resourceOptions={modelKeys} />
    </div>
  );
}

export default ModelGrantsPage;
