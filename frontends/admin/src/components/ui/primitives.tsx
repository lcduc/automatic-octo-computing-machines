/** Small presentational building blocks shared by every page. */
import { CircleAlert, Inbox, Loader2 } from "lucide-react";
import { cloneElement, isValidElement, useId, type KeyboardEvent, type ReactElement, type ReactNode } from "react";
import { useI18n } from "../../i18n/I18nProvider";

export type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "gold";

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={tone === "neutral" ? "badge" : `badge badge--${tone}`}>{children}</span>;
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {description && <p className="page-header__description">{description}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </header>
  );
}

export function Card({ title, actions, children, flush }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; flush?: boolean }) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card__header">
          {typeof title === "string" ? <h2>{title}</h2> : title}
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {flush ? children : <div className="card__body">{children}</div>}
    </section>
  );
}

export function Spinner({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <span className="row muted" role="status">
      <Loader2 size={16} className="spin" aria-hidden />
      {label ?? t("common.loading")}
    </span>
  );
}

export function LoadingState() {
  return (
    <div className="state">
      <Spinner />
    </div>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="state">
      <span className="state__icon">
        <Inbox size={22} aria-hidden />
      </span>
      <strong>{title}</strong>
      {hint && <span className="small">{hint}</span>}
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const { t } = useI18n();
  return (
    <div className="state state--error" role="alert">
      <CircleAlert size={22} aria-hidden />
      <span>{message}</span>
      {onRetry && (
        <button type="button" className="btn btn--sm" onClick={onRetry}>
          {t("common.retry")}
        </button>
      )}
    </div>
  );
}

export function Callout({ tone = "info", children }: { tone?: "info" | "warning" | "danger"; children: ReactNode }) {
  return (
    <div className={tone === "info" ? "callout" : `callout callout--${tone}`} role={tone === "danger" ? "alert" : undefined}>
      <CircleAlert size={18} aria-hidden />
      <div>{children}</div>
    </div>
  );
}

/**
 * Label + control + hint/error. The control gets the generated id so the label
 * and descriptions are announced by screen readers.
 */
export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: ReactElement<Record<string, unknown>> }) {
  const id = useId();
  const described = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") || undefined;
  const control = isValidElement(children)
    ? cloneElement(children, { id, "aria-describedby": described, "aria-invalid": error ? true : undefined })
    : children;
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      {control}
      {hint && (
        <span id={`${id}-hint`} className="field__hint">
          {hint}
        </span>
      )}
      {error && (
        <span id={`${id}-error`} className="field__error">
          {error}
        </span>
      )}
    </div>
  );
}

export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (value: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className="switch"
      disabled={disabled}
      onClick={() => onChange(!checked)}
    />
  );
}

export function KpiCard({ icon, label, value, hint, tone }: { icon: ReactNode; label: string; value: string; hint?: string; tone?: "gold" | "teal" | "rose" }) {
  return (
    <div className={tone ? `card kpi kpi--${tone}` : "card kpi"}>
      <div className="kpi__head">
        <span className="kpi__label">{label}</span>
        <span aria-hidden>{icon}</span>
      </div>
      <div className="kpi__value">{value}</div>
      {hint && <div className="kpi__hint">{hint}</div>}
    </div>
  );
}

export function JsonBlock({ value }: { value: unknown }) {
  return <pre className="json">{value === null || value === undefined ? "—" : JSON.stringify(value, null, 2)}</pre>;
}

export function Pagination({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (offset: number) => void }) {
  const { t } = useI18n();
  if (total <= limit) return null;
  const from = offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <nav className="pagination" aria-label={t("common.pagination")}>
      <span>{t("common.range", { from, to, total })}</span>
      <div className="row">
        <button type="button" className="btn btn--sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
          {t("common.previous")}
        </button>
        <button type="button" className="btn btn--sm" disabled={to >= total} onClick={() => onChange(offset + limit)}>
          {t("common.next")}
        </button>
      </div>
    </nav>
  );
}

export interface TabItem<K extends string> {
  key: K;
  label: string;
}

/** ARIA tablist; the caller renders the selected panel. */
export function Tabs<K extends string>({ tabs, selected, onSelect, label }: { tabs: TabItem<K>[]; selected: K; onSelect: (key: K) => void; label: string }) {
  const onKeyDown = (event: KeyboardEvent, index: number) => {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    const next = tabs[(index + step + tabs.length) % tabs.length];
    if (next) onSelect(next.key);
  };
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((tab, index) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          className="tab"
          aria-selected={tab.key === selected}
          tabIndex={tab.key === selected ? 0 : -1}
          onClick={() => onSelect(tab.key)}
          onKeyDown={(event) => onKeyDown(event, index)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
