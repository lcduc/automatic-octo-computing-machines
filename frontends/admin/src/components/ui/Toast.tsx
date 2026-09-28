import { CheckCircle2, CircleAlert } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

type ToastKind = "success" | "error";
interface ToastItem {
  id: number;
  kind: ToastKind;
  text: string;
}
interface ToastApi {
  success: (text: string) => void;
  error: (text: string) => void;
}

/** How long a toast stays on screen. */
const TOAST_MS = 4500;
const ToastContext = createContext<ToastApi | null>(null);

/** One place for transient feedback (no alert(), no per-page toasts). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const push = useCallback((kind: ToastKind, text: string) => {
    const id = Date.now() + Math.random();
    setItems((current) => [...current, { id, kind, text }]);
    window.setTimeout(() => setItems((current) => current.filter((item) => item.id !== id)), TOAST_MS);
  }, []);

  const api = useMemo<ToastApi>(
    () => ({ success: (text) => push("success", text), error: (text) => push("error", text) }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className={item.kind === "error" ? "toast toast--error" : "toast"}>
            {item.kind === "error" ? <CircleAlert size={18} aria-hidden /> : <CheckCircle2 size={18} aria-hidden />}
            <span>{item.text}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast must be used inside ToastProvider");
  return value;
}
