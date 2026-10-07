import { Check, Minus } from "lucide-react";
import { NAV_GROUPS } from "../../components/layout/Sidebar";
import { Modal } from "../../components/ui/Modal";
import { useI18n } from "../../i18n/I18nProvider";
import { capabilitiesFor } from "../../lib/permissions";
import type { Role } from "../../lib/types";
import { MATRIX_ROWS } from "./RoleMatrix";

interface RolePreviewDialogProps {
  role: Role;
  onClose: () => void;
}

/** Read-only preview of what a role may do and which pages it sees; nothing is switched or impersonated. */
export function RolePreviewDialog({ role, onClose }: RolePreviewDialogProps) {
  const { t } = useI18n();
  const capabilities = capabilitiesFor(role);
  const groups = NAV_GROUPS.map((group) => ({
    label: group.label,
    items: group.items.filter((item) => !item.requires || capabilities[item.requires]),
  })).filter((group) => group.items.length > 0);

  return (
    <Modal title={t("access.viewAsTitle", { role: t(`role.${role}`) })} onClose={onClose}>
      <p className="small muted">{t(`role.${role}.hint`)}</p>
      <h3>{t("access.viewAsPermissions")}</h3>
      <ul className="stack">
        {MATRIX_ROWS.map((row) => {
          const allowed = row.capability === null || capabilities[row.capability];
          return (
            <li key={row.label} className="row">
              {allowed ? <Check size={16} className="matrix__yes" aria-hidden /> : <Minus size={16} className="muted" aria-hidden />}
              <span className={allowed ? undefined : "muted"}>{t(row.label)}</span>
              <span className="sr-only">{allowed ? t("common.yes") : t("common.no")}</span>
            </li>
          );
        })}
      </ul>
      <h3>{t("access.viewAsPages")}</h3>
      {groups.map((group) => (
        <p key={group.label} className="small">
          <strong>{t(group.label)}:</strong> {group.items.map((item) => t(item.label)).join(", ")}
        </p>
      ))}
    </Modal>
  );
}
