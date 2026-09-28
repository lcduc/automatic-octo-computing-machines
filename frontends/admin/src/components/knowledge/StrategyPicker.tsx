/**
 * Choose a chunking strategy and its parameters. The parameter form is built
 * from the JSON schema the backend publishes (GET knowledge/chunking/strategies),
 * so new parameters appear without frontend changes.
 */
import { useI18n, type Translate } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/vi";
import type { ChunkingSpec, ChunkingStrategyInfo, SchemaProperty } from "../../lib/types";
import { Field } from "../ui/primitives";

const STRATEGY_KEYS: Record<string, MessageKey> = {
  auto: "strategy.auto",
  size: "strategy.size",
  heading: "strategy.heading",
  legal_article: "strategy.legal_article",
  qa_pair: "strategy.qa_pair",
  table_rows: "strategy.table_rows",
  whole: "strategy.whole",
};
const STRATEGY_HINT_KEYS: Record<string, MessageKey> = {
  auto: "strategy.auto.hint",
  size: "strategy.size.hint",
  heading: "strategy.heading.hint",
  legal_article: "strategy.legal_article.hint",
  qa_pair: "strategy.qa_pair.hint",
  table_rows: "strategy.table_rows.hint",
  whole: "strategy.whole.hint",
};
const PARAM_KEYS: Record<string, MessageKey> = {
  max_chars: "param.max_chars",
  overlap: "param.overlap",
  max_level: "param.max_level",
  split_at: "param.split_at",
  breadcrumb: "param.breadcrumb",
  rows_per_chunk: "param.rows_per_chunk",
};
const OPTION_KEYS: Record<string, MessageKey> = {
  chapter: "param.split_at.chapter",
  section: "param.split_at.section",
  article: "param.split_at.article",
  clause: "param.split_at.clause",
};

export function strategyLabel(t: Translate, name: string | undefined): string {
  const key = STRATEGY_KEYS[name ?? "auto"];
  return key ? t(key) : (name ?? "auto");
}

/** Defaults for a strategy's parameters, taken from its schema. */
export function defaultSpec(info: ChunkingStrategyInfo): ChunkingSpec {
  const spec: ChunkingSpec = { strategy: info.name };
  for (const [name, property] of Object.entries(info.params_schema.properties ?? {})) {
    if (name !== "strategy" && property.default !== undefined) spec[name] = property.default;
  }
  return spec;
}

interface StrategyPickerProps {
  strategies: ChunkingStrategyInfo[];
  value: ChunkingSpec;
  onChange: (value: ChunkingSpec) => void;
  disabled?: boolean;
}

export function StrategyPicker({ strategies, value, onChange, disabled }: StrategyPickerProps) {
  const { t } = useI18n();
  const selected = strategies.find((info) => info.name === value.strategy);
  const properties = Object.entries(selected?.params_schema.properties ?? {}).filter(([name]) => name !== "strategy");

  const choose = (name: string) => {
    const info = strategies.find((item) => item.name === name);
    if (info) onChange(defaultSpec(info));
  };

  return (
    <div className="stack">
      <Field label={t("chunking.strategy")} hint={STRATEGY_HINT_KEYS[value.strategy] ? t(STRATEGY_HINT_KEYS[value.strategy]!) : selected?.description}>
        <select className="select" value={value.strategy} onChange={(event) => choose(event.target.value)} disabled={disabled}>
          {strategies.map((info) => (
            <option key={info.name} value={info.name}>
              {strategyLabel(t, info.name)}
            </option>
          ))}
        </select>
      </Field>
      {properties.length > 0 && (
        <div className="form-grid">
          {properties.map(([name, property]) => (
            <ParamInput
              key={name}
              name={name}
              property={property}
              value={value[name]}
              disabled={disabled}
              onChange={(next) => onChange({ ...value, [name]: next })}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ParamInput({ name, property, value, onChange, disabled }: { name: string; property: SchemaProperty; value: unknown; onChange: (value: unknown) => void; disabled?: boolean }) {
  const { t } = useI18n();
  const label = PARAM_KEYS[name] ? t(PARAM_KEYS[name]!) : (property.title ?? name);

  if (property.type === "boolean") {
    return (
      <label className="checkbox">
        <input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} disabled={disabled} />
        {label}
      </label>
    );
  }
  if (property.enum) {
    return (
      <Field label={label}>
        <select className="select" value={String(value ?? property.default ?? "")} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
          {property.enum.map((option) => (
            <option key={String(option)} value={String(option)}>
              {OPTION_KEYS[String(option)] ? t(OPTION_KEYS[String(option)]!) : String(option)}
            </option>
          ))}
        </select>
      </Field>
    );
  }
  const range = property.minimum !== undefined && property.maximum !== undefined ? `${property.minimum}–${property.maximum}` : undefined;
  return (
    <Field label={label} hint={range}>
      <input
        className="input"
        type="number"
        min={property.minimum}
        max={property.maximum}
        step={property.type === "integer" ? 1 : "any"}
        value={value === undefined || value === null ? "" : String(value)}
        placeholder={t("chunking.defaultValue")}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value === "" ? undefined : Number(event.target.value))}
      />
    </Field>
  );
}
