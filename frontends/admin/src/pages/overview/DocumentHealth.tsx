import { Link } from "react-router";
import { Card, ErrorState, LoadingState } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { KnowledgeHealth } from "../../lib/types";
import { useApi } from "../../lib/use-api";

const HEALTH_DAYS = 30;
const LIST_LIMIT = 10;

interface Row {
  id: string;
  title: string;
  detail: string;
}

function DocumentList({ title, rows, empty, total }: { title: string; rows: Row[]; empty: string; total?: number }) {
  const { t, formatNumber } = useI18n();
  return (
    <section>
      <h3 className="small">
        {title}
        {total !== undefined && <span className="muted"> · {t("overview.docHealth.count", { count: formatNumber(total) })}</span>}
      </h3>
      {rows.length === 0 ? (
        <p className="muted small">{empty}</p>
      ) : (
        <ul className="breakdown">
          {rows.map((row) => (
            <li key={row.id} className="breakdown__row">
              <Link className="breakdown__label" to={`/knowledge/${row.id}`}>
                {row.title}
              </Link>
              <span className="breakdown__value">{row.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Which documents are cited, never cited, tied to thumbs-down answers, expiring or scheduled (last 30 days). */
export function DocumentHealth() {
  const { t, formatNumber } = useI18n();
  const health = useApi<KnowledgeHealth>(`knowledge/health?days=${HEALTH_DAYS}&limit=${LIST_LIMIT}`);
  const title = t("overview.docHealth.title", { days: HEALTH_DAYS });
  const empty = t("overview.docHealth.empty");

  if (health.error) {
    return (
      <Card title={title}>
        <ErrorState message={health.error} onRetry={health.reload} />
      </Card>
    );
  }
  if (!health.data) {
    return (
      <Card title={title}>
        <LoadingState />
      </Card>
    );
  }
  const data = health.data;

  return (
    <Card title={title}>
      <p className="small muted">
        {t("overview.docHealth.summary", { documents: formatNumber(data.documents), disabled: formatNumber(data.disabled), failed: formatNumber(data.failed) })}
      </p>
      <div className="grid-2 mt-3">
        <DocumentList
          title={t("overview.docHealth.mostCited")}
          empty={empty}
          rows={data.most_cited.map((doc) => ({ id: doc.document_id, title: doc.title, detail: formatNumber(doc.citations) }))}
        />
        <DocumentList
          title={t("overview.docHealth.neverCited")}
          empty={empty}
          total={data.never_cited.count}
          rows={data.never_cited.items.map((doc) => ({ id: doc.document_id, title: doc.title, detail: doc.created_at.slice(0, 10) }))}
        />
        <DocumentList
          title={t("overview.docHealth.notHelpful")}
          empty={empty}
          rows={data.not_helpful.map((doc) => ({ id: doc.document_id, title: doc.title, detail: formatNumber(doc.count) }))}
        />
        <DocumentList
          title={t("overview.docHealth.expiring")}
          empty={empty}
          rows={data.expiring.map((doc) => ({ id: doc.document_id, title: doc.title, detail: doc.effective_to }))}
        />
        <DocumentList
          title={t("overview.docHealth.scheduled")}
          empty={empty}
          rows={data.scheduled.map((doc) => ({ id: doc.document_id, title: doc.title, detail: doc.effective_from }))}
        />
      </div>
    </Card>
  );
}
