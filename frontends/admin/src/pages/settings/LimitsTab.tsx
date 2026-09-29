import { Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Callout, Card, ErrorState, Field, LoadingState } from "../../components/ui/primitives";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/vi";
import { adminApi } from "../../lib/api";
import { useSession } from "../../lib/session";
import type { ModelPrice, Settings, UsageSummary } from "../../lib/types";
import { useApi } from "../../lib/use-api";
import { useSaveSettings } from "./use-save-settings";

type LimitKey =
  | "limit_anonymous_per_minute"
  | "limit_anonymous_per_hour"
  | "tokens_anonymous_per_day"
  | "limit_user_per_minute"
  | "limit_user_per_hour"
  | "tokens_user_per_day"
  | "tokens_ip_per_day";
type SpendKey = "spend_cap_monthly_usd" | "spend_anonymous_cutoff_ratio";

const LIMITS: Array<{ key: LimitKey; label: MessageKey }> = [
  { key: "limit_anonymous_per_minute", label: "limits.anonymousPerMinute" },
  { key: "limit_anonymous_per_hour", label: "limits.anonymousPerHour" },
  { key: "tokens_anonymous_per_day", label: "limits.anonymousTokens" },
  { key: "limit_user_per_minute", label: "limits.userPerMinute" },
  { key: "limit_user_per_hour", label: "limits.userPerHour" },
  { key: "tokens_user_per_day", label: "limits.userTokens" },
  { key: "tokens_ip_per_day", label: "limits.ipTokens" },
];
const MICRO_USD_PER_USD = 1_000_000;

function usd(microUsd: number): string {
  return `$${(microUsd / MICRO_USD_PER_USD).toFixed(2)}`;
}

interface LimitsTabProps {
  settings: Settings;
  onSaved: (settings: Settings) => void;
}

/** Per-tier limits, the monthly spend cap and the model price table (SEC-08, ADM-08, ADM-09). */
export function LimitsTab({ settings, onSaved }: LimitsTabProps) {
  const { t } = useI18n();
  const { canWrite } = useSession();
  const { save, saving, error } = useSaveSettings(onSaved);
  const [draft, setDraft] = useState(settings);
  const usage = useApi<UsageSummary>("usage/summary?days=1");
  const changed = (keys: Array<LimitKey | SpendKey>) => keys.filter((key) => draft[key] !== settings[key]);
  const saveKeys = (keys: Array<LimitKey | SpendKey>) =>
    void save(Object.fromEntries(changed(keys).map((key) => [key, draft[key]])));
  const cap = settings.spend_cap_monthly_usd * MICRO_USD_PER_USD;
  const spent = usage.data?.month.cost_micro_usd ?? 0;

  return (
    <div className="grid-2">
      <Card title={t("limits.title")}>
        <form className="stack" onSubmit={(event) => { event.preventDefault(); saveKeys(LIMITS.map((item) => item.key)); }}>
          <p className="small muted">{t("limits.help")}</p>
          {LIMITS.map((item) => (
            <Field key={item.key} label={t(item.label)}>
              <input className="input" type="number" min={0} required value={draft[item.key]} disabled={!canWrite || saving}
                onChange={(e) => setDraft({ ...draft, [item.key]: Number(e.target.value) })} />
            </Field>
          ))}
          {canWrite && (
            <div>
              <button type="submit" className="btn btn--primary" disabled={saving || changed(LIMITS.map((item) => item.key)).length === 0}>
                {saving ? t("common.saving") : t("limits.save")}
              </button>
            </div>
          )}
        </form>
      </Card>

      <div className="stack">
        <Card title={t("limits.spendTitle")}>
          <form className="stack" onSubmit={(event) => { event.preventDefault(); saveKeys(["spend_cap_monthly_usd", "spend_anonymous_cutoff_ratio"]); }}>
            <p className="small">
              {t("limits.spentThisMonth", { spent: usd(spent), cap: cap > 0 ? usd(cap) : t("limits.noCap") })}
            </p>
            <Field label={t("limits.cap")} hint={t("limits.capHint")}>
              <input className="input" type="number" min={0} step="0.01" required value={draft.spend_cap_monthly_usd} disabled={!canWrite || saving}
                onChange={(e) => setDraft({ ...draft, spend_cap_monthly_usd: Number(e.target.value) })} />
            </Field>
            <Field label={t("limits.cutoff")} hint={t("limits.cutoffHint")}>
              <input className="input" type="number" min={0} max={1} step="0.05" required value={draft.spend_anonymous_cutoff_ratio} disabled={!canWrite || saving}
                onChange={(e) => setDraft({ ...draft, spend_anonymous_cutoff_ratio: Number(e.target.value) })} />
            </Field>
            {error && <Callout tone="danger">{error}</Callout>}
            {canWrite && (
              <div>
                <button type="submit" className="btn btn--primary" disabled={saving || changed(["spend_cap_monthly_usd", "spend_anonymous_cutoff_ratio"]).length === 0}>
                  {saving ? t("common.saving") : t("limits.save")}
                </button>
              </div>
            )}
          </form>
        </Card>
        <PricesCard />
      </div>
    </div>
  );
}

function PricesCard() {
  const { t } = useI18n();
  const { isOwner } = useSession();
  const toast = useToast();
  const prices = useApi<ModelPrice[]>("prices");
  const [model, setModel] = useState("");
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const body = { input_usd_per_million: input, output_usd_per_million: output };
      await adminApi(`prices/${model.trim()}`, { method: "PUT", body });
      toast.success(t("limits.priceSaved", { model }));
      setModel("");
      setInput("");
      setOutput("");
      prices.reload();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  const remove = async (price: ModelPrice) => {
    try {
      await adminApi(`prices/${price.model}`, { method: "DELETE" });
      prices.reload();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  return (
    <Card title={t("limits.pricesTitle")} flush>
      <p className="card__body small muted">{t("limits.pricesHelp")}</p>
      {prices.error && <ErrorState message={prices.error} onRetry={prices.reload} />}
      {prices.loading && <LoadingState />}
      {prices.data && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t("limits.model")}</th>
                <th scope="col">{t("limits.inputPrice")}</th>
                <th scope="col">{t("limits.outputPrice")}</th>
                {isOwner && <th scope="col">{t("common.actions")}</th>}
              </tr>
            </thead>
            <tbody>
              {prices.data.map((price) => (
                <tr key={price.model}>
                  <td className="mono">{price.model}</td>
                  <td>${price.input_usd_per_million}</td>
                  <td>${price.output_usd_per_million}</td>
                  {isOwner && (
                    <td>
                      <button type="button" className="btn btn--sm btn--ghost" aria-label={t("limits.removePrice", { model: price.model })} onClick={() => void remove(price)}>
                        <Trash2 size={14} aria-hidden />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {isOwner && (
        <form className="card__body toolbar" onSubmit={submit}>
          <Field label={t("limits.model")}>
            <input className="input mono" required maxLength={100} pattern="[A-Za-z0-9._:/\-]+" value={model} onChange={(e) => setModel(e.target.value)} />
          </Field>
          <Field label={t("limits.inputPrice")}>
            <input className="input" type="number" min={0} step="0.000001" required value={input} onChange={(e) => setInput(e.target.value)} />
          </Field>
          <Field label={t("limits.outputPrice")}>
            <input className="input" type="number" min={0} step="0.000001" required value={output} onChange={(e) => setOutput(e.target.value)} />
          </Field>
          <button type="submit" className="btn btn--primary">{t("limits.setPrice")}</button>
        </form>
      )}
    </Card>
  );
}
