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
  onClose: () => void;
}

/** Which knowledge sources answer the chat: the switch turns a source on or off for every visitor. */
export function SourcesDrawer({ sources, onClose }: SourcesDrawerProps) {
  const { t } = useI18n();
  const { canWrite } = useSession();
  const toast = useToast();

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
              <div>
                <strong>{source.name}</strong>
                {source.description && <span className="small muted"> — {source.description}</span>}
                <span className="small muted source-list__meta">
                  {t("chat.sourceDocuments", { count: source.document_count })} · {t("chat.sourcePriority", { priority: source.priority })}
                </span>
              </div>
              {canWrite ? (
                <Switch checked={source.enabled} onChange={(value) => void setEnabled(source, value)} label={t("chat.sourceSwitch", { name: source.name })} />
              ) : (
                <Badge tone={source.enabled ? "success" : "neutral"}>{source.enabled ? t("common.on") : t("common.off")}</Badge>
              )}
            </li>
          ))}
        </ul>
      )}
      <Link to="/knowledge?tab=sources" className="small">
        {t("chat.manageSources")}
      </Link>
    </Drawer>
  );
}
