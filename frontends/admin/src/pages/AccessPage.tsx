import { Copy, KeyRound, UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Modal } from "../components/ui/Modal";
import { Badge, Callout, Card, ErrorState, Field, LoadingState, PageHeader } from "../components/ui/primitives";
import { useToast } from "../components/ui/Toast";
import { useI18n } from "../i18n/I18nProvider";
import { adminApi } from "../lib/api";
import { useSession } from "../lib/session";
import { ROLES, type AdminUser, type ApiKey, type ApiKeyCreated, type Role } from "../lib/types";
import { useApi } from "../lib/use-api";

/** Same rule as the backend (AdminCreate.password). */
const MIN_PASSWORD_LENGTH = 10;

function Users() {
  const { t, formatDateTime } = useI18n();
  const { admin } = useSession();
  const toast = useToast();
  const users = useApi<AdminUser[]>("users");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("viewer");

  const update = async (user: AdminUser, changes: Partial<Pick<AdminUser, "role" | "disabled">>) => {
    try {
      await adminApi(`users/${user.id}`, { method: "PATCH", body: changes });
      toast.success(t("access.userUpdated", { email: user.email }));
      users.reload();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  const create = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await adminApi("users", { method: "POST", body: { email, password, role } });
      toast.success(t("access.userCreated", { email }));
      setEmail("");
      setPassword("");
      users.reload();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  return (
    <Card title={t("access.users")} flush>
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <form className="card__body toolbar" onSubmit={create}>
        <Field label={t("access.email")}>
          <input className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
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
        <button type="submit" className="btn btn--primary">
          <UserPlus size={16} aria-hidden />
          {t("access.addUser")}
        </button>
      </form>
    </Card>
  );
}

function ApiKeys() {
  const { t, formatDateTime } = useI18n();
  const toast = useToast();
  const keys = useApi<ApiKey[]>("api-keys");
  const [name, setName] = useState("");
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setCreated(await adminApi<ApiKeyCreated>("api-keys", { method: "POST", body: { name } }));
      setName("");
      keys.reload();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

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
                <th scope="col">{t("access.lastUsed")}</th>
                <th scope="col">{t("access.state")}</th>
              </tr>
            </thead>
            <tbody>
              {keys.data.map((key) => (
                <tr key={key.id}>
                  <td>{key.name}</td>
                  <td className="mono">{key.key_prefix}…</td>
                  <td className="small muted">{formatDateTime(key.last_used_at)}</td>
                  <td>
                    {key.revoked_at ? (
                      <Badge tone="danger">{t("access.revoked")}</Badge>
                    ) : (
                      <button type="button" className="btn btn--sm btn--danger" onClick={() => void revoke(key)}>
                        {t("access.revoke")}
                      </button>
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
      <ApiKeys />
    </>
  );
}
