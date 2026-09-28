import { useState, type FormEvent } from "react";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import { Modal } from "../ui/Modal";
import { Callout, Field } from "../ui/primitives";
import { useToast } from "../ui/Toast";

/** Same rule as the backend (``PasswordChange.new_password``). */
const MIN_PASSWORD_LENGTH = 10;

export function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (next.length < MIN_PASSWORD_LENGTH) return setError(t("account.passwordTooShort", { min: MIN_PASSWORD_LENGTH }));
    if (next !== confirm) return setError(t("account.passwordMismatch"));
    setBusy(true);
    setError(null);
    try {
      await adminApi("auth/password", { method: "POST", body: { current_password: current, new_password: next } });
      toast.success(t("account.passwordChanged"));
      onClose();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={t("account.changePassword")} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        {error && <Callout tone="danger">{error}</Callout>}
        <Field label={t("account.currentPassword")}>
          <input className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required data-autofocus />
        </Field>
        <Field label={t("account.newPassword")} hint={t("account.passwordHint", { min: MIN_PASSWORD_LENGTH })}>
          <input className="input" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />
        </Field>
        <Field label={t("account.confirmPassword")}>
          <input className="input" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        </Field>
        <div className="row row--between">
          <button type="button" className="btn" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button type="submit" className="btn btn--primary" disabled={busy}>
            {t("common.save")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
