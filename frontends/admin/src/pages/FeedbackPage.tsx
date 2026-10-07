import { CircleCheck, FlaskConical, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Badge, EmptyState, ErrorState, Field, LoadingState, PageHeader, Pagination } from "../components/ui/primitives";
import { useToast } from "../components/ui/Toast";
import { useI18n } from "../i18n/I18nProvider";
import { adminApi, query } from "../lib/api";
import { useSession } from "../lib/session";
import type { FeedbackItem, Page } from "../lib/types";
import { useApi } from "../lib/use-api";
import { EvalCasesCard } from "./feedback/EvalCasesCard";

const PAGE_SIZE = 50;

/** Visitor ratings, newest first; thumbs-down answers are the ones to fix (ADM-10, ADM-12). */
export function FeedbackPage() {
  const { t, formatDateTime } = useI18n();
  const { canWrite } = useSession();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const rating = params.get("rating") ?? "";
  const reviewed = params.get("reviewed") ?? "";
  const offset = Number(params.get("offset") ?? 0);
  const { data, error, loading, reload } = useApi<Page<FeedbackItem>>(
    `feedback${query({ rating: rating || undefined, reviewed: reviewed || undefined, limit: PAGE_SIZE, offset })}`,
  );
  const [evalVersion, setEvalVersion] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);

  const act = async (item: FeedbackItem, action: "review" | "eval") => {
    setBusy(item.id);
    try {
      if (action === "review") {
        await adminApi(`feedback/${item.id}`, { method: "PATCH", body: { reviewed: !item.reviewed_at } });
        reload();
      } else {
        await adminApi(`messages/${item.message_id}/eval-case`, { method: "POST", body: {} });
        toast.success(t("feedback.addedToEval"));
        setEvalVersion((value) => value + 1);
        reload();
      }
    } catch (reason) {
      toast.error((reason as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const filter = (changes: Record<string, string>) => setParams({ rating, reviewed, ...changes });

  return (
    <>
      <PageHeader title={t("feedback.title")} description={t("feedback.description")} />
      <div className="toolbar">
        <Field label={t("feedback.rating")}>
          <select className="select" value={rating} onChange={(e) => filter({ rating: e.target.value })}>
            <option value="-1">{t("feedback.negative")}</option>
            <option value="1">{t("feedback.positive")}</option>
            <option value="">{t("common.all")}</option>
          </select>
        </Field>
        <Field label={t("feedback.reviewState")}>
          <select className="select" value={reviewed} onChange={(e) => filter({ reviewed: e.target.value })}>
            <option value="false">{t("feedback.unreviewed")}</option>
            <option value="true">{t("feedback.reviewed")}</option>
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
                  {canWrite && <th scope="col">{t("common.actions")}</th>}
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
                    <td className="small muted">
                      {formatDateTime(item.created_at)}
                      {item.reviewed_at && <div>{t("feedback.reviewedBy", { who: item.reviewed_by ?? "—" })}</div>}
                    </td>
                    {canWrite && (
                      <td>
                        <button type="button" className="btn btn--sm" disabled={busy === item.id} onClick={() => void act(item, "review")}>
                          <CircleCheck size={14} aria-hidden />
                          {item.reviewed_at ? t("feedback.markUnreviewed") : t("feedback.markReviewed")}
                        </button>
                        <button type="button" className="btn btn--sm btn--ghost" disabled={busy === item.id || !item.question || item.in_eval_set} onClick={() => void act(item, "eval")}>
                          <FlaskConical size={14} aria-hidden />
                          {item.in_eval_set ? t("feedback.inEval") : t("feedback.addToEval")}
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && <Pagination total={data.total} limit={PAGE_SIZE} offset={offset} onChange={(value) => setParams({ rating, reviewed, offset: String(value) })} />}
      </section>
      <EvalCasesCard key={evalVersion} onRemoved={reload} />
    </>
  );
}
