import { Check, Minus } from "lucide-react";
import { Card } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/vi";
import { capabilitiesFor, type Capabilities } from "../../lib/permissions";
import { ROLES } from "../../lib/types";

/** Rows of the matrix: reading is open to every role, the rest follow `capabilitiesFor`. */
export const MATRIX_ROWS: Array<{ label: MessageKey; capability: keyof Capabilities | null }> = [
  { label: "matrix.read", capability: null },
  { label: "matrix.handoff", capability: "canHandoff" },
  { label: "matrix.write", capability: "canWrite" },
  { label: "matrix.owner", capability: "isOwner" },
];

/** Read-only view of what each role may do (the backend enforces the same rules). */
export function RoleMatrix() {
  const { t } = useI18n();
  return (
    <Card title={t("matrix.title")} flush>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">{t("matrix.permission")}</th>
              {ROLES.map((role) => (
                <th key={role} scope="col" className="table__center">
                  <span className={`role-chip role--${role}`}>{t(`role.${role}`)}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {MATRIX_ROWS.map((row) => (
              <tr key={row.label}>
                <th scope="row">{t(row.label)}</th>
                {ROLES.map((role) => {
                  const allowed = row.capability === null || capabilitiesFor(role)[row.capability];
                  return (
                    <td key={role} className="table__center" aria-label={allowed ? t("common.yes") : t("common.no")}>
                      {allowed ? <Check size={16} className="matrix__yes" aria-hidden /> : <Minus size={16} className="muted" aria-hidden />}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
