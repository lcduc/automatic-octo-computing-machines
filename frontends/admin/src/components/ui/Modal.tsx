import { X } from "lucide-react";
import { useId, useRef, type ReactNode } from "react";
import { useI18n } from "../../i18n/I18nProvider";
import { useDialogFocus } from "./use-dialog-focus";

interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}

/** Centered dialog with a focus trap; closes on Escape, the close button or the backdrop. */
export function Modal({ title, onClose, children, footer, wide }: ModalProps) {
  const { t } = useI18n();
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useDialogFocus(ref, onClose);

  return (
    <div className="overlay" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div ref={ref} className={wide ? "modal modal--wide" : "modal"} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <div className="modal__header">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="btn btn--ghost btn--icon" onClick={onClose} aria-label={t("common.close")}>
            <X size={18} aria-hidden />
          </button>
        </div>
        <div className="modal__body">{children}</div>
        {footer && <div className="modal__footer">{footer}</div>}
      </div>
    </div>
  );
}

interface DrawerProps {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  /** Pinned under the scrolling body (e.g. a reply composer). */
  footer?: ReactNode;
}

/** Right-hand panel for details (handoffs, audit entries); same keyboard rules as a modal. */
export function Drawer({ title, onClose, children, footer }: DrawerProps) {
  const { t } = useI18n();
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useDialogFocus(ref, onClose);

  return (
    <>
      <div className="drawer-overlay" onMouseDown={onClose} aria-hidden />
      <aside ref={ref} className="drawer" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <div className="drawer__header">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="btn btn--ghost btn--icon" onClick={onClose} aria-label={t("common.close")}>
            <X size={18} aria-hidden />
          </button>
        </div>
        <div className="drawer__body">{children}</div>
        {footer && <div className="drawer__footer">{footer}</div>}
      </aside>
    </>
  );
}

interface ConfirmProps {
  title: string;
  message: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Replaces window.confirm with an accessible dialog. */
export function ConfirmDialog({ title, message, confirmLabel, danger, busy, onConfirm, onCancel }: ConfirmProps) {
  const { t } = useI18n();
  return (
    <Modal
      title={title}
      onClose={onCancel}
      footer={
        <>
          <button type="button" className="btn" onClick={onCancel}>
            {t("common.cancel")}
          </button>
          <button type="button" className={danger ? "btn btn--danger" : "btn btn--primary"} onClick={onConfirm} disabled={busy} data-autofocus>
            {confirmLabel}
          </button>
        </>
      }
    >
      <div>{message}</div>
    </Modal>
  );
}
