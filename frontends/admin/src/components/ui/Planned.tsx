/**
 * Features shown for completeness (they exist in the giz-chatbot console) but
 * not backed by an API yet: visible, clearly marked, and never actionable.
 */
import { Hourglass, type LucideIcon } from "lucide-react";
import { useId, type ReactNode } from "react";
import { useI18n } from "../../i18n/I18nProvider";

/** Small tag saying the feature waits for backend support. */
export function PlannedBadge() {
  const { t } = useI18n();
  return (
    <span className="planned-badge" title={t("planned.hint")}>
      <Hourglass size={11} aria-hidden />
      {t("planned.badge")}
    </span>
  );
}

/** A disabled button with the planned tag; screen readers hear why it does nothing. */
export function PlannedButton({ icon: Icon, label, small, danger }: { icon?: LucideIcon; label: string; small?: boolean; danger?: boolean }) {
  const { t } = useI18n();
  const hintId = useId();
  const classes = ["btn", small && "btn--sm", danger && "btn--danger", "btn--planned"].filter(Boolean).join(" ");
  return (
    <button type="button" className={classes} disabled aria-describedby={hintId} title={t("planned.hint")}>
      {Icon && <Icon size={small ? 14 : 16} aria-hidden />}
      {label}
      <span id={hintId} className="sr-only">
        {t("planned.hint")}
      </span>
    </button>
  );
}

/** A section of planned controls, dimmed, with the explanation above it. */
export function PlannedSection({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="planned-section">
      <p className="planned-section__note small">
        <PlannedBadge /> {t("planned.hint")}
      </p>
      <div className="planned-section__body">{children}</div>
    </div>
  );
}
