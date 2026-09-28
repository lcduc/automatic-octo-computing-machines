import { Bell, ChevronRight, KeyRound, Languages, LogOut, Menu } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useMatches } from "react-router";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/vi";
import { useSession } from "../../lib/session";
import { ChangePasswordModal } from "./ChangePasswordModal";

export interface RouteHandle {
  crumb?: MessageKey;
}

interface TopBarProps {
  onMenu: () => void;
  pendingHandoffs: number;
  failedDocuments: number;
}

function useDismiss(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => ref.current && !ref.current.contains(event.target as Node) && close();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && close();
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);
  return ref;
}

export function TopBar({ onMenu, pendingHandoffs, failedDocuments }: TopBarProps) {
  const { t, language, setLanguage } = useI18n();
  const { admin, signOut } = useSession();
  const matches = useMatches();
  const [menuOpen, setMenuOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);
  const menuRef = useDismiss(menuOpen, () => setMenuOpen(false));
  const bellRef = useDismiss(bellOpen, () => setBellOpen(false));

  const crumbs = matches
    .map((match) => (match.handle as RouteHandle | undefined)?.crumb)
    .filter((crumb): crumb is MessageKey => Boolean(crumb));
  const alerts = pendingHandoffs + failedDocuments;

  return (
    <header className="topbar">
      <button type="button" className="btn btn--ghost btn--icon topbar__menu" onClick={onMenu} aria-label={t("nav.open")}>
        <Menu size={20} aria-hidden />
      </button>
      <ol className="breadcrumb" aria-label={t("nav.breadcrumb")}>
        <li>{t("app.title")}</li>
        {crumbs.map((crumb) => (
          <li key={crumb} className="row">
            <ChevronRight size={14} aria-hidden />
            {t(crumb)}
          </li>
        ))}
      </ol>
      <div className="topbar__actions">
        <button
          type="button"
          className="btn btn--sm"
          onClick={() => setLanguage(language === "vi" ? "en" : "vi")}
          aria-label={t("topbar.language")}
        >
          <Languages size={15} aria-hidden />
          {language === "vi" ? "EN" : "VI"}
        </button>

        <div className="relative" ref={bellRef}>
          <button
            type="button"
            className="btn btn--ghost btn--icon"
            aria-label={t("topbar.notifications", { count: alerts })}
            aria-expanded={bellOpen}
            onClick={() => setBellOpen((value) => !value)}
          >
            <Bell size={18} aria-hidden />
            {alerts > 0 && <span className="nav-item__badge">{alerts}</span>}
          </button>
          {bellOpen && (
            <div className="menu">
              <div className="menu__header">
                <strong>{t("topbar.notificationsTitle")}</strong>
              </div>
              {alerts === 0 && <p className="menu__item muted">{t("topbar.noNotifications")}</p>}
              {pendingHandoffs > 0 && (
                <Link className="menu__item" to="/handoffs?status=pending" onClick={() => setBellOpen(false)}>
                  {t("topbar.pendingHandoffs", { count: pendingHandoffs })}
                </Link>
              )}
              {failedDocuments > 0 && (
                <Link className="menu__item" to="/knowledge?status=failed" onClick={() => setBellOpen(false)}>
                  {t("topbar.failedDocuments", { count: failedDocuments })}
                </Link>
              )}
            </div>
          )}
        </div>

        <div className="relative" ref={menuRef}>
          <button type="button" className="user-pill" aria-expanded={menuOpen} onClick={() => setMenuOpen((value) => !value)}>
            <span className="avatar" aria-hidden>
              {admin.email.slice(0, 1)}
            </span>
            <span className="small">{t(`role.${admin.role}`)}</span>
          </button>
          {menuOpen && (
            <div className="menu">
              <div className="menu__header">
                <div className="truncate">{admin.email}</div>
                <div className="small muted">{t(`role.${admin.role}`)}</div>
              </div>
              <button
                type="button"
                className="menu__item"
                onClick={() => {
                  setMenuOpen(false);
                  setChangingPassword(true);
                }}
              >
                <KeyRound size={15} aria-hidden />
                {t("account.changePassword")}
              </button>
              <button type="button" className="menu__item" onClick={() => void signOut()}>
                <LogOut size={15} aria-hidden />
                {t("account.signOut")}
              </button>
            </div>
          )}
        </div>
      </div>
      {changingPassword && <ChangePasswordModal onClose={() => setChangingPassword(false)} />}
    </header>
  );
}
