/** Convert metadata to editable rows and back (pure; validated like the backend's validate_metadata). */
import type { MessageKey } from "../i18n/vi";
import type { Metadata } from "./types";

export type ValueType = "text" | "number" | "boolean" | "list";

export interface MetadataRow {
  key: string;
  value: string;
  type: ValueType;
}

/** Same rule as the backend: identifier-like, at most 64 characters. */
const KEY_PATTERN = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;
/** Same limit as the backend. */
export const MAX_METADATA_KEYS = 30;

export function toRows(metadata: Metadata): MetadataRow[] {
  return Object.entries(metadata).map(([key, value]) => ({
    key,
    value: Array.isArray(value) ? value.join(", ") : value === null ? "" : String(value),
    type: Array.isArray(value) ? "list" : typeof value === "number" ? "number" : typeof value === "boolean" ? "boolean" : "text",
  }));
}

export interface MetadataResult {
  metadata?: Metadata;
  error?: { key: MessageKey; params: Record<string, string | number> };
}

/** Rows back to metadata, or the first problem found (blank rows are skipped). */
export function fromRows(rows: MetadataRow[]): MetadataResult {
  const metadata: Metadata = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (!key && !row.value.trim()) continue;
    if (!KEY_PATTERN.test(key)) return { error: { key: "metadata.invalidKey", params: { key } } };
    if (key in metadata) return { error: { key: "metadata.duplicateKey", params: { key } } };
    if (row.type === "number") {
      const number = Number(row.value);
      if (row.value.trim() === "" || !Number.isFinite(number)) return { error: { key: "metadata.notNumber", params: { key } } };
      metadata[key] = number;
    } else if (row.type === "boolean") {
      metadata[key] = row.value === "true";
    } else if (row.type === "list") {
      metadata[key] = row.value.split(",").map((item) => item.trim()).filter(Boolean);
    } else {
      metadata[key] = row.value;
    }
  }
  if (Object.keys(metadata).length > MAX_METADATA_KEYS) {
    return { error: { key: "metadata.tooMany", params: { max: MAX_METADATA_KEYS } } };
  }
  return { metadata };
}
