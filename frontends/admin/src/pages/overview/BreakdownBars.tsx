import { useI18n } from "../../i18n/I18nProvider";

const PERCENT = 100;

/**
 * One `{name: amount}` breakdown as horizontal bars, largest first.
 *
 * @param counts - Amount per name (e.g. turns per route).
 * @param label - Display text for a name.
 * @param format - Display text for an amount; plain number by default.
 * @param empty - Shown when there is nothing to draw.
 */
export function BreakdownBars({
  counts,
  label,
  format,
  empty,
}: {
  counts: Record<string, number>;
  label: (name: string) => string;
  format?: (amount: number) => string;
  empty: string;
}) {
  const { formatNumber } = useI18n();
  const rows = Object.entries(counts)
    .filter(([, amount]) => amount > 0)
    .sort(([, a], [, b]) => b - a);
  if (rows.length === 0) return <p className="muted small">{empty}</p>;

  const total = rows.reduce((sum, [, amount]) => sum + amount, 0);
  const largest = rows[0]?.[1] ?? 1;
  return (
    <ul className="breakdown">
      {rows.map(([name, amount]) => (
        <li key={name} className="breakdown__row">
          <span className="breakdown__label">{label(name)}</span>
          <span className="breakdown__value">
            {format ? format(amount) : formatNumber(amount)} · {formatNumber((amount / total) * PERCENT, 0)}%
          </span>
          <span className="breakdown__track" aria-hidden>
            <span className="breakdown__bar" style={{ width: `${(amount / largest) * PERCENT}%` }} />
          </span>
        </li>
      ))}
    </ul>
  );
}
