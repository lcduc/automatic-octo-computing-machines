import { useCallback, useEffect, useState } from "react";
import { adminApi } from "./api";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  /** True only until the first result for the current path arrives. */
  loading: boolean;
  reload: () => void;
  setData: (value: T | null) => void;
}

/**
 * Load an admin endpoint and expose loading/error state plus a reload function.
 *
 * @param path - Endpoint path, or null to skip loading.
 * @param refreshMs - Reload this often while mounted (e.g. while documents are processing).
 */
export function useApi<T>(path: string | null, refreshMs?: number): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadedPath, setLoadedPath] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    adminApi<T>(path, { signal: controller.signal })
      .then((result) => {
        setData(result);
        setError(null);
        setLoadedPath(path);
      })
      .catch((reason: Error) => {
        if (reason.name === "AbortError") return;
        setError(reason.message);
        setLoadedPath(path);
      });
    return () => controller.abort();
    // `version` is the reload trigger: bumping it must re-run the request.
    // oxlint-disable-next-line react/exhaustive-effect-dependencies
  }, [path, version]);

  useEffect(() => {
    if (!refreshMs || !path) return;
    const timer = window.setInterval(() => setVersion((value) => value + 1), refreshMs);
    return () => window.clearInterval(timer);
  }, [refreshMs, path]);

  const reload = useCallback(() => setVersion((value) => value + 1), []);
  return { data, error, loading: Boolean(path) && loadedPath !== path, reload, setData };
}
