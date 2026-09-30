import { UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Modal } from "../../components/ui/Modal";
import { Callout, Field } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import { ROLES, type Role } from "../../lib/types";

/** Same rule as the backend (AdminCreate.password). */
const MIN_PASSWORD_LENGTH = 10;
const FORM_ID = "new-user-form";

interface NewUserDialogProps {
  onClose: () => void;
  onCreated: (email: string) => void;
}

/** Create an admin account; stays open with the error shown if the backend refuses. */
export function NewUserDialog({ onClose, onCreated }: NewUserDialogProps) {
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await adminApi("users", { method: "POST", body: { email, password, role } });
      onCreated(email);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={t("access.addUser")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button type="submit" form={FORM_ID} className="btn btn--primary" disabled={saving}>
            <UserPlus size={16} aria-hidden />
            {t("access.addUser")}
          </button>
        </>
      }
    >
      <form id={FORM_ID} className="stack" onSubmit={submit}>
        {error && <Callout tone="danger">{error}</Callout>}
        <Field label={t("access.email")}>
          <input className="input" type="email" autoComplete="off" required autoFocus data-autofocus value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label={t("access.initialPassword")} hint={t("account.passwordHint", { min: MIN_PASSWORD_LENGTH })}>
          <input className="input" type="password" autoComplete="new-password" required minLength={MIN_PASSWORD_LENGTH} value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label={t("access.role")} hint={t(`role.${role}.hint`)}>
          <select className="select" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.map((value) => (
              <option key={value} value={value}>
                {t(`role.${value}`)}
              </option>
            ))}
          </select>
        </Field>
      </form>
    </Modal>
  );
}
