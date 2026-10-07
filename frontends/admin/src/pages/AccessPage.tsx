import { Copy, Eye, KeyRound, RefreshCw, UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Modal } from "../components/ui/Modal";
import { Badge, Callout, Card, ErrorState, Field, LoadingState, PageHeader } from "../components/ui/primitives";
import { useToast } from "../components/ui/Toast";
import { useI18n } from "../i18n/I18nProvider";
import { adminApi } from "../lib/api";
import { useSession } from "../lib/session";
import { API_KEY_SCOPES, ROLES, type AdminUser, type ApiKey, type ApiKeyCreated, type ApiKeyScope, type Role } from "../lib/types";
import { useApi } from "../lib/use-api";
import { NewUserDialog } from "./access/NewUserDialog";
import { RoleMatrix } from "./access/RoleMatrix";
import { RolePreviewDialog } from "./access/RolePreviewDialog";

/** Same defaults and bounds as the backend (ApiKeyCreate / ApiKeyRotate). */
const DEFAULT_KEY_RATE_LIMIT = 60;
const MAX_KEY_RATE_LIMIT = 10_000;
const MAX_KEY_LIFETIME_DAYS = 3650;
const ROTATION_GRACE_DAYS = 7;

function Users() {
  const { t, formatDateTime } = useI18n();
  const { admin } = useSession();
  const toast = useToast();
  const users = useApi<AdminUser[]>("users");
  const [creating, setCreating] = useState(false);
  const [previewRole, setPreviewRole] = useState<Role | null>(null);

  const update = async (user: AdminUser, changes: Partial<Pick<AdminUser, "role" | "disabled">>) => {
    try {
      await adminApi(`users/${user.id}`, { method: "PATCH", body: changes });
      toast.success(t("access.userUpdated", { email: user.email }));
      users.reload();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  return (
    <Card
      title={t("access.users")}
      flush
      actions={
        <button type="button" className="btn btn--primary btn--sm" onClick={() => setCreating(true)}>
          <UserPlus size={16} aria-hidden />
          {t("access.addUser")}
        </button>
      }
    >
      {users.error && <ErrorState message={users.error} onRetry={users.reload} />}
      {users.loading && <LoadingState />}
      {users.data && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t("access.email")}</th>
                <th scope="col">{t("access.role")}</th>
                <th scope="col">{t("access.lastLogin")}</th>
                <th scope="col">{t("access.state")}</th>
                <th scope="col">{t("access.more")}</th>
              </tr>
            </thead>
            <tbody>
              {users.data.map((user) => (
                <tr key={user.id}>
                  <td>
                    {user.email}
                    {user.id === admin.id && <Badge tone="gold">{t("access.you")}</Badge>}
                  </td>
                  <td>
                    <select className="select" aria-label={t("access.roleFor", { email: user.email })} value={user.role} onChange={(e) => void update(user, { role: e.target.value as Role })}>
                      {ROLES.map((value) => (
                        <option key={value} value={value}>
                          {t(`role.${value}`)}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="small muted">{formatDateTime(user.last_login_at)}</td>
                  <td>
                    <button type="button" className={user.disabled ? "btn btn--sm" : "btn btn--sm btn--danger"} disabled={user.id === admin.id} onClick={() => void update(user, { disabled: !user.disabled })}>
                      {user.disabled ? t("access.enable") : t("access.disable")}
                    </button>
                  </td>
                  <td>
                    <button type="button" className="btn btn--sm" onClick={() => setPreviewRole(user.role)}>
                      <Eye size={14} aria-hidden />
                      {t("access.viewAs")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {previewRole && <RolePreviewDialog role={previewRole} onClose={() => setPreviewRole(null)} />}
      {creating && (
        <NewUserDialog
          onClose={() => setCreating(false)}
          onCreated={(email) => {
            setCreating(false);
            toast.success(t("access.userCreated", { email }));
            users.reload();
          }}
        />
      )}
    </Card>
  );
}

function ApiKeys() {
  const { t, formatDateTime } = useI18n();
  const toast = useToast();
  const keys = useApi<ApiKey[]>("api-keys");
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<ApiKeyScope[]>([]);
  const [rateLimit, setRateLimit] = useState(DEFAULT_KEY_RATE_LIMIT);
  const [expiresInDays, setExpiresInDays] = useState("");
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);

  const toggleScope = (scope: ApiKeyScope, on: boolean) =>
    setScopes((current) => (on ? [...current, scope] : current.filter((item) => item !== scope)));

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (scopes.length === 0) {
      toast.error(t("access.pickScope"));
      return;
    }
    try {
      const body = { name, scopes, rate_limit_per_minute: rateLimit, expires_in_days: expiresInDays ? Number(expiresInDays) : null };
      setCreated(await adminApi<ApiKeyCreated>("api-keys", { method: "POST", body }));
      setName("");
      setScopes([]);
      setExpiresInDays("");
      keys.reload();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  const rotate = async (key: ApiKey) => {
    try {
      const body = { grace_days: ROTATION_GRACE_DAYS };
      setCreated(await adminApi<ApiKeyCreated>(`api-keys/${key.id}/rotate`, { method: "POST", body }));
      toast.success(t("access.keyRotated", { name: key.name }));
      keys.reload();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  const inactive = (key: ApiKey) => key.revoked_at !== null || (key.expires_at !== null && new Date(key.expires_at) <= new Date());

  const revoke = async (key: ApiKey) => {
    try {
      await adminApi(`api-keys/${key.id}/revoke`, { method: "POST" });
      toast.success(t("access.keyRevoked", { name: key.name }));
      keys.reload();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(t("access.copied"));
    } catch {
      toast.error(t("access.copyFailed"));
    }
  };

  return (
    <Card title={t("access.keys")} flush>
      <p className="card__body small muted">{t("access.keysHelp")}</p>
      {keys.error && <ErrorState message={keys.error} onRetry={keys.reload} />}
      {keys.loading && <LoadingState />}
      {keys.data && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t("access.keyName")}</th>
                <th scope="col">{t("access.keyPrefix")}</th>
                <th scope="col">{t("access.keyScopes")}</th>
                <th scope="col">{t("access.rateLimit")}</th>
                <th scope="col">{t("access.expires")}</th>
                <th scope="col">{t("access.lastUsed")}</th>
                <th scope="col">{t("access.state")}</th>
              </tr>
            </thead>
            <tbody>
              {keys.data.map((key) => (
                <tr key={key.id}>
                  <td>{key.name}</td>
                  <td className="mono">{key.key_prefix}…</td>
                  <td className="small">{key.scopes.map((scope) => t(`access.scope.${scope}`)).join(", ")}</td>
                  <td className="small">{key.rate_limit_per_minute}</td>
                  <td className="small muted">{key.expires_at ? formatDateTime(key.expires_at) : t("access.never")}</td>
                  <td className="small muted">{formatDateTime(key.last_used_at)}</td>
                  <td>
                    {key.revoked_at ? (
                      <Badge tone="danger">{t("access.revoked")}</Badge>
                    ) : inactive(key) ? (
                      <Badge tone="danger">{t("access.expired")}</Badge>
                    ) : (
                      <div className="toolbar">
                        <button type="button" className="btn btn--sm" title={t("access.rotateHint", { days: ROTATION_GRACE_DAYS })} onClick={() => void rotate(key)}>
                          <RefreshCw size={14} aria-hidden />
                          {t("access.rotate")}
                        </button>
                        <button type="button" className="btn btn--sm btn--danger" onClick={() => void revoke(key)}>
                          {t("access.revoke")}
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <form className="card__body toolbar" onSubmit={create}>
        <Field label={t("access.keyName")} hint={t("access.keyNameHint")}>
          <input className="input" required maxLength={128} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <fieldset className="field">
          <legend className="field__label">{t("access.keyScopes")}</legend>
          {API_KEY_SCOPES.map((scope) => (
            <label key={scope} className="checkbox">
              <input type="checkbox" checked={scopes.includes(scope)} onChange={(e) => toggleScope(scope, e.target.checked)} />
              {t(`access.scope.${scope}`)}
            </label>
          ))}
        </fieldset>
        <Field label={t("access.rateLimit")} hint={t("access.rateLimitHint")}>
          <input className="input" type="number" min={1} max={MAX_KEY_RATE_LIMIT} required value={rateLimit} onChange={(e) => setRateLimit(Number(e.target.value))} />
        </Field>
        <Field label={t("access.expiresInDays")} hint={t("access.expiresHint")}>
          <input className="input" type="number" min={1} max={MAX_KEY_LIFETIME_DAYS} value={expiresInDays} onChange={(e) => setExpiresInDays(e.target.value)} />
        </Field>
        <button type="submit" className="btn btn--primary">
          <KeyRound size={16} aria-hidden />
          {t("access.createKey")}
        </button>
      </form>
      {created && (
        <Modal title={t("access.newKey")} onClose={() => setCreated(null)}>
          <Callout tone="warning">{t("access.newKeyWarning")}</Callout>
          <pre className="json">{created.key}</pre>
          <div>
            <button type="button" className="btn" onClick={() => void copy(created.key)}>
              <Copy size={16} aria-hidden />
              {t("access.copy")}
            </button>
          </div>
        </Modal>
      )}
    </Card>
  );
}

export function AccessPage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("access.title")} description={t("access.description")} />
      <Users />
      <RoleMatrix />
      <ApiKeys />
    </>
  );
}
