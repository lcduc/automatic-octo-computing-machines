import { Bot } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { Callout, Field } from "../components/ui/primitives";
import { useI18n } from "../i18n/I18nProvider";
import { adminApi, ApiError } from "../lib/api";

/** Only same-app paths are followed after sign-in (never an absolute URL). */
function safeNext(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/";
}

export function LoginPage() {
  const { t, language, setLanguage } = useI18n();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // The backend sets the HttpOnly session cookie; the token in the body is not kept.
      await adminApi("auth/login", { method: "POST", body: { email, password }, allowUnauthorized: true });
      navigate(safeNext(params.get("next")), { replace: true });
    } catch (reason) {
      setError(reason instanceof ApiError && reason.status === 401 ? t("login.invalid") : (reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login">
      <form className="card login__card" onSubmit={submit}>
        <div className="row">
          <span className="kpi__icon kpi__icon--gold" aria-hidden>
            <Bot size={20} />
          </span>
          <div>
            <h1>{t("login.title")}</h1>
            <p className="muted small">{t("login.subtitle")}</p>
          </div>
        </div>
        {error && <Callout tone="danger">{error}</Callout>}
        <Field label={t("login.email")}>
          <input className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
        </Field>
        <Field label={t("login.password")}>
          <input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        <button type="submit" className="btn btn--primary" disabled={busy}>
          {busy ? t("login.signingIn") : t("login.submit")}
        </button>
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => setLanguage(language === "vi" ? "en" : "vi")}>
          {language === "vi" ? "English" : "Tiếng Việt"}
        </button>
      </form>
    </main>
  );
}
