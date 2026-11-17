import { useState } from "react";
import { useSearchParams } from "react-router";
import { ErrorState, Field, LoadingState, PageHeader, Tabs } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { DailyMetrics, UsageSummary } from "../../lib/types";
import { useApi } from "../../lib/use-api";
import { BusinessTab } from "./BusinessTab";
import { QualityTab } from "./QualityTab";
import { SystemTab } from "./SystemTab";

const PERIODS = [1, 7, 30] as const;
const TABS = ["overview", "quality", "system"] as const;
type Tab = (typeof TABS)[number];

/** The tab named in `?tab=`, or the business overview. */
function selectedTab(value: string | null): Tab {
  return (TABS as readonly string[]).includes(value ?? "") ? (value as Tab) : "overview";
}

/** Dashboards for one period, split by reader: business, quality and system. */
export function OverviewPage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const tab = selectedTab(params.get("tab"));
  const [days, setDays] = useState<(typeof PERIODS)[number]>(7);
  const summary = useApi<UsageSummary>(`usage/summary?days=${days}`);
  const history = useApi<DailyMetrics[]>(`usage/history?days=${days}`);
  const error = summary.error ?? history.error;
  const data = summary.data && history.data ? { summary: summary.data, history: history.data } : null;

  return (
    <>
      <PageHeader
        title={t("overview.title")}
        description={t("overview.description")}
        actions={
          <Field label={t("overview.period")}>
            <select className="select" value={days} onChange={(event) => setDays(Number(event.target.value) as (typeof PERIODS)[number])}>
              {PERIODS.map((period) => (
                <option key={period} value={period}>
                  {t(`overview.period.${period}`)}
                </option>
              ))}
            </select>
          </Field>
        }
      />
      <Tabs<Tab>
        label={t("overview.tabs")}
        tabs={TABS.map((key) => ({ key, label: t(`overview.tab.${key}`) }))}
        selected={tab}
        onSelect={(key) => setParams(key === "overview" ? {} : { tab: key })}
      />

      {error && (
        <ErrorState
          message={error}
          onRetry={() => {
            summary.reload();
            history.reload();
          }}
        />
      )}
      {!data && !error && <LoadingState />}
      {data && tab === "overview" && <BusinessTab {...data} />}
      {data && tab === "quality" && <QualityTab {...data} />}
      {data && tab === "system" && <SystemTab {...data} />}
    </>
  );
}
