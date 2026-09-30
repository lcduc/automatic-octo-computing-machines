import { Link } from "react-router";
import { Drawer } from "../../components/ui/Modal";
import { Badge, Callout, ErrorState, LoadingState, Switch } from "../../components/ui/primitives";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import { useSession } from "../../lib/session";
import type { Source } from "../../lib/types";
import type { ApiState } from "../../lib/use-api";

interface SourcesDrawerProps {
  sources: ApiState<Source[]>;
  /** Names this chat is limited to; empty means every enabled source. */
  selected: string[];
  onSelect: (names: string[]) => void;
  onClose: () => void;
}

/**
 * Which knowledge sources answer the demo chat. Ticking limits only this
 * conversation (the `sources` filter of a chat request); the switch turns a
 * source on or off for every visitor.
 */
export function SourcesDrawer({ sources, selected, onSelect, onClose }: SourcesDrawerProps) {
  const { t } = useI18n();
  const { canWrite } = useSession();
  const toast = useToast();

  const toggleSelected = (name: string) =>
    onSelect(selected.includes(name) ? selected.filter((item) => item !== name) : [...selected, name]);

  const setEnabled = async (source: Source, enabled: boolean) => {
    try {
      const updated = await adminApi<Source>(`knowledge/sources/${source.id}`, { method: "PATCH", body: { enabled } });
      sources.setData((sources.data ?? []).map((item) => (item.id === updated.id ? updated : item)));
      toast.success(t(enabled ? "chat.sourceEnabled" : "chat.sourceDisabled", { name: source.name }));
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  return (
    <Drawer title={t("chat.sourcesTitle")} onClose={onClose}>
      <Callout>{t("chat.sourcesHelp")}</Callout>
      {sources.error && <ErrorState message={sources.error} onRetry={sources.reload} />}
      {sources.loading && <LoadingState />}
      {sources.data && (
        <ul className="source-list">
          {sources.data.map((source) => (
            <li key={source.id} className="source-list__item">
              <label className="checkbox source-list__pick">
                <input type="checkbox" checked={selected.includes(source.name)} disabled={!source.enabled} onChange={() => toggleSelected(source.name)} />
                <span>
                  <strong>{source.name}</strong>
                  {source.description && <span className="small muted"> — {source.description}</span>}
                  <span className="small muted source-list__meta">
                    {t("chat.sourceDocuments", { count: source.document_count })} · {t("chat.sourcePriority", { priority: source.priority })}
                  </span>
                </span>
              </label>
              {canWrite ? (
                <Switch checked={source.enabled} onChange={(value) => void setEnabled(source, value)} label={t("chat.sourceSwitch", { name: source.name })} />
              ) : (
                <Badge tone={source.enabled ? "success" : "neutral"}>{source.enabled ? t("common.on") : t("common.off")}</Badge>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="row row--between">
        <button type="button" className="btn btn--sm" onClick={() => onSelect([])} disabled={!selected.length}>
          {t("chat.useAllSources")}
        </button>
        <Link to="/knowledge?tab=sources" className="small">
          {t("chat.manageSources")}
        </Link>
      </div>
    </Drawer>
  );
}
