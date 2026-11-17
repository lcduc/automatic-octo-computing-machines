import { useI18n } from "../../i18n/I18nProvider";
import { STEP_ORDER, stepLabel } from "../../lib/labels";
import type { StepPercentiles } from "./rollup";

/** p50 and p95 per pipeline step in pipeline order, then any step this admin does not know. */
export function StepLatencyTable({ steps }: { steps: Record<string, StepPercentiles> }) {
  const { t, formatNumber } = useI18n();
  const names = [...STEP_ORDER.filter((step) => step in steps), ...Object.keys(steps).filter((step) => !STEP_ORDER.includes(step))];
  if (names.length === 0) return <p className="muted small">{t("overview.noData")}</p>;

  const ms = (value: number) => `${formatNumber(Math.round(value))} ms`;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>{t("overview.stepColumn")}</th>
            <th>p50</th>
            <th>p95</th>
          </tr>
        </thead>
        <tbody>
          {names.map((step) => {
            const key = stepLabel(step);
            return (
              <tr key={step}>
                <td>{key ? t(key) : step}</td>
                <td>{ms(steps[step]!.p50)}</td>
                <td>{ms(steps[step]!.p95)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
