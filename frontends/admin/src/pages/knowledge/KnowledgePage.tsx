import { useSearchParams } from "react-router";
import { ErrorState, LoadingState, PageHeader, Tabs } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { Source } from "../../lib/types";
import { useApi } from "../../lib/use-api";
import { DocumentsTab } from "./DocumentsTab";
import { SourcesTab } from "./SourcesTab";

type Tab = "documents" | "sources";

export function KnowledgePage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "sources" ? "sources" : "documents";
  const sources = useApi<Source[]>("knowledge/sources");

  return (
    <>
      <PageHeader title={t("knowledge.title")} description={t("knowledge.description")} />
      <Tabs<Tab>
        label={t("knowledge.title")}
        tabs={[
          { key: "documents", label: t("knowledge.documents") },
          { key: "sources", label: t("knowledge.sources") },
        ]}
        selected={tab}
        onSelect={(key) => setParams(key === "documents" ? {} : { tab: key })}
      />
      {sources.error && <ErrorState message={sources.error} onRetry={sources.reload} />}
      {!sources.data && !sources.error && <LoadingState />}
      {sources.data && tab === "documents" && <DocumentsTab sources={sources.data} />}
      {sources.data && tab === "sources" && <SourcesTab sources={sources.data} onChanged={sources.reload} />}
    </>
  );
}
