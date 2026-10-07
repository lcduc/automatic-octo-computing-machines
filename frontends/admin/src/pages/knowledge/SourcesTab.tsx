import { Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ConfirmDialog } from "../../components/ui/Modal";
import { Callout, Field, Switch } from "../../components/ui/primitives";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import { useSession } from "../../lib/session";
import type { Source } from "../../lib/types";

/** Same rule as the backend's SOURCE_NAME_PATTERN. */
const NAME_PATTERN = "^[A-Za-z0-9_\\-]{1,64}$";

function SourceRow({ source, onChanged }: { source: Source; onChanged: () => void }) {
  const { t, formatNumber } = useI18n();
  const { canWrite } = useSession();
  const toast = useToast();
  const [description, setDescription] = useState(source.description);
  const [priority, setPriority] = useState(String(source.priority));
  const [confirmDelete, setConfirmDelete] = useState(false);
  const dirty = description !== source.description || Number(priority) !== source.priority;

  const save = async (changes: Partial<Source>) => {
    try {
      await adminApi(`knowledge/sources/${source.id}`, { method: "PATCH", body: changes });
      toast.success(t("sources.saved", { name: source.name }));
      onChanged();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  const remove = async () => {
    setConfirmDelete(false);
    try {
      await adminApi(`knowledge/sources/${source.id}`, { method: "DELETE" });
      onChanged();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  return (
    <tr>
      <td>
        <strong>{source.name}</strong>
        <div className="small muted">{t("sources.documents", { count: formatNumber(source.document_count) })}</div>
      </td>
      <td>
        <input className="input" aria-label={t("sources.descriptionFor", { name: source.name })} value={description} maxLength={500} disabled={!canWrite} onChange={(e) => setDescription(e.target.value)} />
      </td>
      <td>
        <input className="input" type="number" min={0.1} max={5} step={0.1} aria-label={t("sources.priorityFor", { name: source.name })} value={priority} disabled={!canWrite} onChange={(e) => setPriority(e.target.value)} />
      </td>
      <td>
        <Switch checked={source.enabled} disabled={!canWrite} label={t("sources.enabledFor", { name: source.name })} onChange={(value) => void save({ enabled: value })} />
      </td>
      <td>
        {canWrite && (
          <div className="row">
            <button type="button" className="btn btn--sm" disabled={!dirty} onClick={() => void save({ description, priority: Number(priority) })}>
              {t("common.save")}
            </button>
            <button type="button" className="btn btn--sm btn--danger" disabled={source.document_count > 0} title={source.document_count > 0 ? t("sources.deleteBlocked") : undefined} onClick={() => setConfirmDelete(true)}>
              {t("common.delete")}
            </button>
          </div>
        )}
        {confirmDelete && (
          <ConfirmDialog title={t("sources.delete")} message={t("sources.deleteConfirm", { name: source.name })} confirmLabel={t("common.delete")} danger onConfirm={() => void remove()} onCancel={() => setConfirmDelete(false)} />
        )}
      </td>
    </tr>
  );
}

export function SourcesTab({ sources, onChanged }: { sources: Source[]; onChanged: () => void }) {
  const { t } = useI18n();
  const { canWrite } = useSession();
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const create = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await adminApi("knowledge/sources", { method: "POST", body: { name, description, priority: 1, enabled: true } });
      setName("");
      setDescription("");
      toast.success(t("sources.created", { name }));
      onChanged();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  return (
    <div className="stack">
      <Callout>{t("sources.help")}</Callout>
      <section className="card">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t("sources.name")}</th>
                <th scope="col">{t("sources.description")}</th>
                <th scope="col">{t("sources.priority")}</th>
                <th scope="col">{t("sources.enabled")}</th>
                <th scope="col">
                  <span className="sr-only">{t("common.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => (
                <SourceRow key={`${source.id}-${source.priority}-${source.description}-${source.enabled}`} source={source} onChanged={onChanged} />
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {canWrite && (
        <form className="card card__body toolbar" onSubmit={create}>
          <Field label={t("sources.newName")}>
            <input
              className="input"
              required
              pattern={NAME_PATTERN}
              placeholder={t("sources.nameHint")}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label={t("sources.description")}>
            <input className="input" maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <button type="submit" className="btn btn--primary">
            <Plus size={16} aria-hidden />
            {t("sources.add")}
          </button>
        </form>
      )}
    </div>
  );
}
