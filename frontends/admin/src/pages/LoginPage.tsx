import { Eye, EyeOff, Lock } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { ThemeToggle } from "../components/layout/ThemeToggle";
import { PlannedBadge } from "../components/ui/Planned";
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
  const [showPassword, setShowPassword] = useState(false);
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
        <div className="login__head">
          <span className="login__logo" aria-hidden>
            <Lock size={22} />
          </span>
          <h1>{t("login.title")}</h1>
          <p className="muted small">{t("login.subtitle")}</p>
        </div>
        {error && <Callout tone="danger">{error}</Callout>}
        <Field label={t("login.email")}>
          <input className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
        </Field>
        <Field label={t("login.password")}>
          <input
            className="input"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </Field>
        <button type="button" className="btn btn--ghost btn--sm login__reveal" aria-pressed={showPassword} onClick={() => setShowPassword((value) => !value)}>
          {showPassword ? <EyeOff size={14} aria-hidden /> : <Eye size={14} aria-hidden />}
          {showPassword ? t("login.hidePassword") : t("login.showPassword")}
        </button>
        <div className="planned-field">
          <Field label={t("login.mfa")} hint={t("planned.hint")}>
            <input className="input" inputMode="numeric" autoComplete="one-time-code" placeholder="123456" disabled />
          </Field>
          <PlannedBadge />
        </div>
        <button type="submit" className="btn btn--primary" disabled={busy}>
          {busy ? t("login.signingIn") : t("login.submit")}
        </button>
        <div className="row row--between">
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => setLanguage(language === "vi" ? "en" : "vi")}>
            {language === "vi" ? "English" : "Tiếng Việt"}
          </button>
          <ThemeToggle className="btn btn--ghost btn--sm btn--icon" />
        </div>
      </form>
    </main>
  );
}
