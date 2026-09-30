import { useCallback, useEffect, useState } from "react";

/**
 * Where the chat widget is served. The admin image is shared by every
 * deployment, so this is read at runtime from `/runtime-config.json`
 * (a static default in dev; generated from WIDGET_ORIGIN by the admin's Caddy).
 */
export const RUNTIME_CONFIG_PATH = "/runtime-config.json";

/** Accept only an http(s) origin, never a path or another scheme. */
export function parseWidgetOrigin(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === "https:" || url.protocol === "http:" ? url.origin : null;
  } catch {
    return null;
  }
}

export function useWidgetOrigin() {
  const [value, setValue] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetch(RUNTIME_CONFIG_PATH, { signal: controller.signal, cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = (await response.json()) as { widgetOrigin?: unknown };
        setValue(parseWidgetOrigin(body.widgetOrigin));
        setError(null);
      })
      .catch((reason: Error) => {
        if (reason.name !== "AbortError") setError(reason.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // `version` is the reload trigger: bumping it must re-run the request.
    // oxlint-disable-next-line react/exhaustive-effect-dependencies
  }, [version]);

  const reload = useCallback(() => {
    setLoading(true);
    setVersion((current) => current + 1);
  }, []);
  return { value, error, loading, reload };
}
