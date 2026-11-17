import { Fragment } from "react";
import { Link } from "react-router";
import { Badge, Card, ErrorState, LoadingState } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/vi";
import type { AuditSummary } from "../../lib/types";
import { useApi } from "../../lib/use-api";

const AUDIT_DAYS = 30;
const COUNTS = ["logins_succeeded", "contact_reveals", "api_key_changes", "account_changes", "deletions", "data_subject_requests", "legal_hold_changes", "denied"] as const;

/** Owner-only counts of sensitive admin actions, with a link to the full audit log. */
export function SecuritySummary() {
  const { t, formatNumber } = useI18n();
  const audit = useApi<AuditSummary>(`audit/summary?days=${AUDIT_DAYS}`);
  const title = t("overview.security.title", { days: AUDIT_DAYS });

  if (audit.error) {
    return (
      <Card title={title}>
        <ErrorState message={audit.error} onRetry={audit.reload} />
      </Card>
    );
  }
  if (!audit.data) {
    return (
      <Card title={title}>
        <LoadingState />
      </Card>
    );
  }
  const data = audit.data;
  const failed = data.logins_failed > 0;

  return (
    <Card title={title} actions={<Link to="/audit">{t("overview.security.viewAudit")}</Link>}>
      <dl className="dl">
        <dt>{t("overview.security.logins_failed")}</dt>
        <dd>
          <Badge tone={failed ? "danger" : "success"}>
            {formatNumber(data.logins_failed)} · {t(failed ? "overview.security.attention" : "overview.security.none")}
          </Badge>
        </dd>
        {COUNTS.map((key) => (
          <Fragment key={key}>
            <dt>{t(`overview.security.${key}` as MessageKey)}</dt>
            <dd>{formatNumber(data[key])}</dd>
          </Fragment>
        ))}
      </dl>
      {data.failed_login_ips.length > 0 && (
        <>
          <h3 className="small mt-3">{t("overview.security.failedIps")}</h3>
          <ul className="breakdown">
            {data.failed_login_ips.map((row) => (
              <li key={row.client_ip} className="breakdown__row">
                <span className="breakdown__label mono">{row.client_ip}</span>
                <span className="breakdown__value">{formatNumber(row.count)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}
