import { useSearchParams } from "react-router";
import { ErrorState, LoadingState, PageHeader, Tabs } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { Settings, SystemStatus } from "../../lib/types";
import { useApi } from "../../lib/use-api";
import { ChatBehaviorTab } from "./ChatBehaviorTab";
import { LimitsTab } from "./LimitsTab";
import { PrivacyTab } from "./PrivacyTab";
import { SupportTab } from "./SupportTab";
import { ToolsTab } from "./ToolsTab";
import { ModelsTab } from "./ModelsTab";
import { WidgetTab } from "./WidgetTab";

type Tab = "chat" | "models" | "limits" | "tools" | "support" | "privacy" | "widget";

export function SettingsPage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const tab = (["chat", "models", "limits", "tools", "support", "privacy", "widget"].includes(params.get("tab") ?? "") ? params.get("tab") : "chat") as Tab;
  const settings = useApi<Settings>("settings");
  const defaults = useApi<Settings>("settings/defaults");
  const system = useApi<SystemStatus>("system");

  return (
    <>
      <PageHeader title={t("settings.title")} description={t("settings.description")} />
      <Tabs<Tab>
        label={t("settings.title")}
        tabs={[
          { key: "chat", label: t("settings.tab.chat") },
          { key: "models", label: t("settings.tab.models") },
          { key: "limits", label: t("settings.tab.limits") },
          { key: "tools", label: t("settings.tab.tools") },
          { key: "support", label: t("settings.tab.support") },
          { key: "privacy", label: t("settings.tab.privacy") },
          { key: "widget", label: t("settings.tab.widget") },
        ]}
        selected={tab}
        onSelect={(key) => setParams({ tab: key })}
      />
      {settings.error && <ErrorState message={settings.error} onRetry={settings.reload} />}
      {!settings.data && !settings.error && <LoadingState />}
      {settings.data && tab === "chat" && <ChatBehaviorTab key={JSON.stringify(settings.data)} settings={settings.data} onSaved={settings.setData} />}
      {settings.data && defaults.data && tab === "models" && (
        <ModelsTab key={JSON.stringify(settings.data)} settings={settings.data} defaults={defaults.data} system={system.data} onSaved={settings.setData} />
      )}
      {settings.data && tab === "limits" && <LimitsTab key={JSON.stringify(settings.data)} settings={settings.data} onSaved={settings.setData} />}
      {tab === "tools" && <ToolsTab />}
      {settings.data && tab === "support" && <SupportTab key={JSON.stringify(settings.data)} settings={settings.data} onSaved={settings.setData} />}
      {settings.data && tab === "privacy" && <PrivacyTab key={JSON.stringify(settings.data)} settings={settings.data} onSaved={settings.setData} />}
      {settings.data && tab === "widget" && <WidgetTab key={JSON.stringify(settings.data)} settings={settings.data} onSaved={settings.setData} />}
    </>
  );
}
