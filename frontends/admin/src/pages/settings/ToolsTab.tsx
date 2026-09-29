import { Badge, Card, ErrorState, LoadingState } from "../../components/ui/primitives";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import { useSession } from "../../lib/session";
import type { SqlTool } from "../../lib/types";
import { useApi } from "../../lib/use-api";

/**
 * SQL tools of this deployment (TOOL-08): switch each on or off without a deploy.
 * Definitions and their SQL are written by the integrator and only shown here for review.
 */
export function ToolsTab() {
  const { t } = useI18n();
  const { canWrite } = useSession();
  const toast = useToast();
  const tools = useApi<SqlTool[]>("tools");

  const toggle = async (tool: SqlTool) => {
    try {
      await adminApi(`tools/${tool.name}`, { method: "PATCH", body: { enabled: !tool.enabled } });
      toast.success(t(tool.enabled ? "tools.disabled" : "tools.enabled", { name: tool.name }));
      tools.reload();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  return (
    <Card title={t("tools.title")} flush>
      <p className="card__body small muted">{t("tools.help")}</p>
      {tools.error && <ErrorState message={tools.error} onRetry={tools.reload} />}
      {tools.loading && <LoadingState />}
      {tools.data && tools.data.length === 0 && <p className="card__body small">{t("tools.none")}</p>}
      {tools.data && tools.data.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t("tools.name")}</th>
                <th scope="col">{t("tools.tier")}</th>
                <th scope="col">{t("tools.sql")}</th>
                <th scope="col">{t("access.state")}</th>
              </tr>
            </thead>
            <tbody>
              {tools.data.map((tool) => (
                <tr key={tool.name}>
                  <td>
                    <div className="mono">{tool.name}</div>
                    <div className="small muted">{tool.description}</div>
                  </td>
                  <td>{tool.required_tier === "anonymous" ? <Badge>{t("tools.public")}</Badge> : <Badge tone="gold">{tool.required_tier}</Badge>}</td>
                  <td>
                    <details aria-label={t("tools.showSql")}>
                      <summary className="small">{t("tools.showSql")}</summary>
                      <pre className="json">{tool.sql_template}</pre>
                      <p className="small muted">{t("tools.columns", { columns: tool.allowed_columns.join(", "), masked: tool.masked_columns.join(", ") || "—" })}</p>
                    </details>
                  </td>
                  <td>
                    <button type="button" className={tool.enabled ? "btn btn--sm btn--danger" : "btn btn--sm btn--primary"} disabled={!canWrite} onClick={() => void toggle(tool)}>
                      {tool.enabled ? t("access.disable") : t("access.enable")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
