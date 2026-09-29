import { Lock, LockOpen } from "lucide-react";
import { useState } from "react";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import { useSession } from "../../lib/session";
import { Badge } from "../ui/primitives";
import { useToast } from "../ui/Toast";

/**
 * Shows the legal-hold state of a conversation or ticket; owners can toggle it
 * (RET-R2). The change is audit-logged by the backend.
 */
export function LegalHoldButton({ path, held, onChange }: { path: string; held: boolean; onChange: (held: boolean) => void }) {
  const { t } = useI18n();
  const { isOwner } = useSession();
  const toast = useToast();
  const [saving, setSaving] = useState(false);

  const toggle = async () => {
    setSaving(true);
    try {
      const updated = await adminApi<{ legal_hold: boolean }>(`${path}/legal-hold`, { method: "PUT", body: { held: !held } });
      toast.success(updated.legal_hold ? t("legalHold.set") : t("legalHold.cleared"));
      onChange(updated.legal_hold);
    } catch (reason) {
      toast.error((reason as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (!isOwner) return held ? <Badge tone="warning">{t("legalHold.badge")}</Badge> : null;
  return (
    <button type="button" className="btn btn--sm" disabled={saving} aria-pressed={held} onClick={() => void toggle()}>
      {held ? <Lock size={14} aria-hidden /> : <LockOpen size={14} aria-hidden />}
      {held ? t("legalHold.release") : t("legalHold.hold")}
    </button>
  );
}
