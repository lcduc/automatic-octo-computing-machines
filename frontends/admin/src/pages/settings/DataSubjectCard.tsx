import { useState } from "react";
import { ConfirmDialog } from "../../components/ui/Modal";
import { Callout, Card, Field } from "../../components/ui/primitives";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import { downloadJson } from "../../lib/download";
import type { DataSubjectDeleted } from "../../lib/types";

interface Subject {
  user_id: string;
  visitor_id: string;
  email: string;
}

/** Only the identifiers that were filled in. */
function identifiers(subject: Subject): Partial<Subject> {
  return Object.fromEntries(Object.entries(subject).map(([key, value]) => [key, value.trim()]).filter(([, value]) => value));
}

/** Export or delete everything about one person (PRV-03); owners only, audit-logged. */
export function DataSubjectCard() {
  const { t } = useI18n();
  const toast = useToast();
  const [subject, setSubject] = useState<Subject>({ user_id: "", visitor_id: "", email: "" });
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<DataSubjectDeleted | null>(null);
  const body = identifiers(subject);
  const empty = Object.keys(body).length === 0;

  const exportData = async () => {
    setBusy(true);
    try {
      downloadJson("data-subject-export.json", await adminApi<unknown>("data-subjects/export", { method: "POST", body }));
    } catch (reason) {
      toast.error((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const deleteData = async () => {
    setBusy(true);
    try {
      setResult(await adminApi<DataSubjectDeleted>("data-subjects/delete", { method: "POST", body }));
      toast.success(t("privacy.deleted"));
    } catch (reason) {
      toast.error((reason as Error).message);
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  };

  return (
    <Card title={t("privacy.subject")}>
      <div className="stack">
        <p className="small muted">{t("privacy.subjectHelp")}</p>
        <Field label={t("privacy.userId")}>
          <input className="input mono" maxLength={128} value={subject.user_id} onChange={(e) => setSubject({ ...subject, user_id: e.target.value })} />
        </Field>
        <Field label={t("privacy.visitorId")}>
          <input className="input mono" maxLength={128} value={subject.visitor_id} onChange={(e) => setSubject({ ...subject, visitor_id: e.target.value })} />
        </Field>
        <Field label={t("privacy.email")}>
          <input className="input" type="email" maxLength={320} value={subject.email} onChange={(e) => setSubject({ ...subject, email: e.target.value })} />
        </Field>
        <div className="toolbar">
          <button type="button" className="btn" disabled={busy || empty} onClick={() => void exportData()}>{t("privacy.export")}</button>
          <button type="button" className="btn btn--danger" disabled={busy || empty} onClick={() => setConfirming(true)}>{t("privacy.delete")}</button>
        </div>
        {result && (
          <Callout tone={result.kept_on_hold ? "warning" : "info"}>
            {t("privacy.deletedCounts", { conversations: result.conversations, tickets: result.tickets, kept: result.kept_on_hold })}
          </Callout>
        )}
      </div>
      {confirming && (
        <ConfirmDialog
          title={t("privacy.delete")}
          message={t("privacy.deleteConfirm")}
          confirmLabel={t("common.delete")}
          danger
          busy={busy}
          onConfirm={() => void deleteData()}
          onCancel={() => setConfirming(false)}
        />
      )}
    </Card>
  );
}
