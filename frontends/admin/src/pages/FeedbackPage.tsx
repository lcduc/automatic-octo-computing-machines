import { ThumbsDown, ThumbsUp } from "lucide-react";
import { Link, useSearchParams } from "react-router";
import { Badge, EmptyState, ErrorState, Field, LoadingState, PageHeader, Pagination } from "../components/ui/primitives";
import { useI18n } from "../i18n/I18nProvider";
import { query } from "../lib/api";
import type { FeedbackItem, Page } from "../lib/types";
import { useApi } from "../lib/use-api";

const PAGE_SIZE = 50;

/** Visitor ratings, newest first; thumbs-down answers are the ones to fix. */
export function FeedbackPage() {
  const { t, formatDateTime } = useI18n();
  const [params, setParams] = useSearchParams();
  const rating = params.get("rating") ?? "-1";
  const offset = Number(params.get("offset") ?? 0);
  const { data, error, loading, reload } = useApi<Page<FeedbackItem>>(`feedback${query({ rating: rating || undefined, limit: PAGE_SIZE, offset })}`);

  return (
    <>
      <PageHeader title={t("feedback.title")} description={t("feedback.description")} />
      <div className="toolbar">
        <Field label={t("feedback.rating")}>
          <select className="select" value={rating} onChange={(e) => setParams({ rating: e.target.value })}>
            <option value="-1">{t("feedback.negative")}</option>
            <option value="1">{t("feedback.positive")}</option>
            <option value="">{t("common.all")}</option>
          </select>
        </Field>
      </div>
      <section className="card">
        {error && <ErrorState message={error} onRetry={reload} />}
        {loading && <LoadingState />}
        {data && data.items.length === 0 && <EmptyState title={t("feedback.empty")} />}
        {data && data.items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t("feedback.rating")}</th>
                  <th scope="col">{t("feedback.question")}</th>
                  <th scope="col">{t("feedback.answer")}</th>
                  <th scope="col">{t("feedback.comment")}</th>
                  <th scope="col">{t("feedback.when")}</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <Badge tone={item.rating > 0 ? "success" : "danger"}>
                        {item.rating > 0 ? <ThumbsUp size={12} aria-hidden /> : <ThumbsDown size={12} aria-hidden />}
                        {item.rating > 0 ? t("feedback.positive") : t("feedback.negative")}
                      </Badge>
                    </td>
                    <td className="prewrap">{item.question ?? "—"}</td>
                    <td>
                      <p className="prewrap small">{item.answer}</p>
                      <Link to={`/conversations/${item.conversation_id}`} className="small">
                        {t("live.open")}
                      </Link>
                    </td>
                    <td className="prewrap">{item.comment ?? "—"}</td>
                    <td className="small muted">{formatDateTime(item.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && <Pagination total={data.total} limit={PAGE_SIZE} offset={offset} onChange={(value) => setParams({ rating, offset: String(value) })} />}
      </section>
    </>
  );
}
