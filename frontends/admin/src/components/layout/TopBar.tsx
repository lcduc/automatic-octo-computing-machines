import { Bell, BellRing, ChevronDown, ChevronRight, KeyRound, LogOut, Menu, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useMatches } from "react-router";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/vi";
import { useSession } from "../../lib/session";
import { useDesktopNotifications } from "../../lib/use-desktop-notifications";
import { QuickUpload } from "../knowledge/QuickUpload";
import { NAV_GROUPS } from "./Sidebar";
import { ThemeToggle } from "./ThemeToggle";

export interface RouteHandle {
  crumb?: MessageKey;
  /** The page fills the whole content area without padding (demo chat). */
  bleed?: boolean;
}

interface TopBarProps {
  onMenu: () => void;
  onChangePassword: () => void;
  pendingHandoffs: number | null;
  failedDocuments: number;
}

/** The sidebar group a page belongs to, shown before its name in the breadcrumb. */
function sectionOf(crumb: MessageKey): MessageKey | null {
  return NAV_GROUPS.find((group) => group.items.some((item) => item.label === crumb))?.label ?? null;
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

export function TopBar({ onMenu, onChangePassword, pendingHandoffs, failedDocuments }: TopBarProps) {
  const { t, language, setLanguage } = useI18n();
  const { admin, signOut, canWrite, isOwner } = useSession();
  const matches = useMatches();
  const [menuOpen, setMenuOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const menuRef = useDismiss(menuOpen, () => setMenuOpen(false));
  const bellRef = useDismiss(bellOpen, () => setBellOpen(false));
  const notificationText = useCallback(
    (count: number) => ({ title: t("app.title"), body: t("topbar.pendingHandoffs", { count }) }),
    [t],
  );
  const desktop = useDesktopNotifications(pendingHandoffs, notificationText);

  const crumb = matches
    .map((match) => (match.handle as RouteHandle | undefined)?.crumb)
    .filter((value): value is MessageKey => Boolean(value))
    .at(-1);
  const section = crumb ? sectionOf(crumb) : null;
  const handoffs = pendingHandoffs ?? 0;
  const alerts = handoffs + failedDocuments;

  return (
    <header className="topbar">
      <button type="button" className="btn btn--ghost btn--icon topbar__menu" onClick={onMenu} aria-label={t("nav.open")}>
        <Menu size={20} aria-hidden />
      </button>
      <ol className="breadcrumb" aria-label={t("nav.breadcrumb")}>
        <li>{t(section ?? "app.title")}</li>
        {crumb && (
          <li>
            <ChevronRight size={14} aria-hidden />
            {t(crumb)}
          </li>
        )}
      </ol>
      <div className="topbar__actions">
        {canWrite && <QuickUpload />}

        <div className="lang-toggle" role="group" aria-label={t("topbar.language")}>
          <button type="button" aria-pressed={language === "vi"} onClick={() => setLanguage("vi")}>
            VI
          </button>
          <button type="button" aria-pressed={language === "en"} onClick={() => setLanguage("en")}>
            EN
          </button>
        </div>

        <ThemeToggle />

        <div className="relative" ref={bellRef}>
          <button
            type="button"
            className="btn btn--ghost btn--icon bell"
            aria-label={t("topbar.notifications", { count: alerts })}
            aria-expanded={bellOpen}
            onClick={() => setBellOpen((value) => !value)}
          >
            <Bell size={18} aria-hidden />
            {alerts > 0 && <span className="bell__count">{alerts}</span>}
          </button>
          {bellOpen && (
            <div className="menu">
              <div className="menu__header">
                <strong>{t("topbar.notificationsTitle")}</strong>
              </div>
              {alerts === 0 && <p className="menu__item muted">{t("topbar.noNotifications")}</p>}
              {handoffs > 0 && (
                <Link className="menu__item" to="/handoffs?status=open" onClick={() => setBellOpen(false)}>
                  {t("topbar.pendingHandoffs", { count: handoffs })}
                </Link>
              )}
              {failedDocuments > 0 && (
                <Link className="menu__item" to="/knowledge?status=failed" onClick={() => setBellOpen(false)}>
                  {t("topbar.failedDocuments", { count: failedDocuments })}
                </Link>
              )}
              {desktop.state === "default" && (
                <button type="button" className="menu__item" onClick={() => void desktop.enable()}>
                  <BellRing size={14} aria-hidden />
                  {t("topbar.enableDesktop")}
                </button>
              )}
              {desktop.state === "granted" && <p className="menu__item small muted">{t("topbar.desktopOn")}</p>}
              {desktop.state === "denied" && <p className="menu__item small muted">{t("topbar.desktopBlocked")}</p>}
            </div>
          )}
        </div>

        <div className="relative" ref={menuRef}>
          <button type="button" className={`user-pill role--${admin.role}`} aria-expanded={menuOpen} onClick={() => setMenuOpen((value) => !value)}>
            <span className="avatar" aria-hidden>
              {admin.email.slice(0, 1)}
            </span>
            <span className="user-pill__text">
              <span className="user-pill__name">{admin.email}</span>
              <span className="user-pill__role">{t(`role.${admin.role}`)}</span>
            </span>
            <ChevronDown size={14} aria-hidden />
          </button>
          {menuOpen && (
            <div className="menu">
              <div className="menu__header">
                <div className="truncate">
                  <strong>{admin.email}</strong>
                </div>
                <span className={`role-chip role--${admin.role}`}>{t(`role.${admin.role}`)}</span>
              </div>
              <button
                type="button"
                className="menu__item"
                onClick={() => {
                  setMenuOpen(false);
                  onChangePassword();
                }}
              >
                <KeyRound size={14} aria-hidden />
                {t("account.changePassword")}
              </button>
              {isOwner && (
                <Link className="menu__item" to="/access" onClick={() => setMenuOpen(false)}>
                  <ShieldCheck size={14} aria-hidden />
                  {t("nav.access")}
                </Link>
              )}
              <button type="button" className="menu__item menu__item--danger" onClick={() => void signOut()}>
                <LogOut size={14} aria-hidden />
                {t("account.signOut")}
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
