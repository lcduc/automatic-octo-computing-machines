import type { CSSProperties } from "react";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/vi";
import { heatLevel, maxCell } from "./rollup";

const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
const HOUR_LABEL_STEP = 3;

/** User messages per weekday (Monday first) x hour of day; darker cells are busier. */
export function TrafficHeatmap({ traffic }: { traffic: number[][] | undefined }) {
  const { t, formatNumber } = useI18n();
  const max = maxCell(traffic);
  if (!traffic || max === 0) return <p className="muted small">{t("overview.noData")}</p>;

  return (
    <div className="table-wrap">
      <table className="heatmap">
        <caption className="sr-only">{t("overview.busiestHoursCaption")}</caption>
        <thead>
          <tr>
            <th scope="col">
              <span className="sr-only">{t("overview.busiestHoursDay")}</span>
            </th>
            {HOURS.map((hour) => (
              <th key={hour} scope="col" className="heatmap__hour">
                {hour % HOUR_LABEL_STEP === 0 ? hour : <span className="sr-only">{hour}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {WEEKDAYS.map((weekday, row) => {
            const dayName = t(`overview.traffic.day.${weekday}` as MessageKey);
            return (
              <tr key={weekday}>
                <th scope="row" className="heatmap__day">
                  {dayName}
                </th>
                {HOURS.map((hour) => {
                  const count = traffic[row]?.[hour] ?? 0;
                  const label = t("overview.trafficCell", { day: dayName, hour: `${hour}:00`, count: formatNumber(count) });
                  return (
                    <td key={hour} className="heatmap__cell" style={{ "--level": heatLevel(count, max) } as CSSProperties} title={label}>
                      <span className="sr-only">{label}</span>
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
