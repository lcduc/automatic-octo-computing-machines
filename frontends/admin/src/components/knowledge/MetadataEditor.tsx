import { Plus, Trash2 } from "lucide-react";
import { useI18n } from "../../i18n/I18nProvider";
import type { MetadataRow, ValueType } from "../../lib/metadata";

/** Common keys suggested to editors; any other key is allowed. */
const SUGGESTED_KEYS = ["url", "effective_date", "expiry_date", "document_number", "department", "tags", "question", "article"];
const TYPES: ValueType[] = ["text", "number", "boolean", "list"];

interface MetadataEditorProps {
  rows: MetadataRow[];
  onChange: (rows: MetadataRow[]) => void;
  idPrefix: string;
  disabled?: boolean;
}

/** Editable key/value list; the model reads these values and citations use `url`. */
export function MetadataEditor({ rows, onChange, idPrefix, disabled }: MetadataEditorProps) {
  const { t } = useI18n();
  const update = (index: number, patch: Partial<MetadataRow>) => onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));

  return (
    <div className="stack">
      <datalist id={`${idPrefix}-keys`}>
        {SUGGESTED_KEYS.map((key) => (
          <option key={key} value={key}>
            {key}
          </option>
        ))}
      </datalist>
      {rows.length === 0 && <p className="small muted">{t("metadata.empty")}</p>}
      {rows.map((row, index) => (
        <div key={index} className="row">
          <input
            className="input"
            aria-label={t("metadata.key")}
            list={`${idPrefix}-keys`}
            value={row.key}
            placeholder="key_name"
            disabled={disabled}
            onChange={(event) => update(index, { key: event.target.value })}
          />
          <select
            className="select"
            aria-label={t("metadata.type")}
            value={row.type}
            disabled={disabled}
            onChange={(event) => {
              const type = event.target.value as ValueType;
              update(index, { type, value: type === "boolean" ? "true" : row.value });
            }}
          >
            {TYPES.map((type) => (
              <option key={type} value={type}>
                {t(`metadata.type.${type}`)}
              </option>
            ))}
          </select>
          {row.type === "boolean" ? (
            <select className="select" aria-label={t("metadata.value")} value={row.value} disabled={disabled} onChange={(event) => update(index, { value: event.target.value })}>
              <option value="true">{t("common.yes")}</option>
              <option value="false">{t("common.no")}</option>
            </select>
          ) : (
            <input
              className="input"
              aria-label={t("metadata.value")}
              value={row.value}
              placeholder={row.type === "list" ? t("metadata.listHint") : ""}
              disabled={disabled}
              onChange={(event) => update(index, { value: event.target.value })}
            />
          )}
          <button
            type="button"
            className="btn btn--ghost btn--icon"
            disabled={disabled}
            aria-label={t("metadata.remove", { key: row.key || index + 1 })}
            onClick={() => onChange(rows.filter((_, i) => i !== index))}
          >
            <Trash2 size={16} aria-hidden />
          </button>
        </div>
      ))}
      <div>
        <button type="button" className="btn btn--sm" disabled={disabled} onClick={() => onChange([...rows, { key: "", value: "", type: "text" }])}>
          <Plus size={14} aria-hidden />
          {t("metadata.add")}
        </button>
      </div>
    </div>
  );
}
