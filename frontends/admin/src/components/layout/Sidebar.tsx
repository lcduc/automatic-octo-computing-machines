import {
  BookOpen,
  ChevronRight,
  Database,
  FileClock,
  Headset,
  KeyRound,
  LayoutDashboard,
  Lock,
  LogOut,
  MessageSquareQuote,
  MessagesSquare,
  MonitorSmartphone,
  ScrollText,
  Settings,
  ShieldCheck,
  Sparkles,
  ThumbsUp,
  type LucideIcon,
} from "lucide-react";
import { NavLink } from "react-router";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/vi";
import type { Capabilities } from "../../lib/permissions";
import { useSession } from "../../lib/session";

/** Colour the item takes when it is the current page (see `.nav-item--*` in shell.css). */
type Accent = "gold" | "blue" | "amber" | "red" | "purple" | "green";

interface NavItem {
  to: string;
  label: MessageKey;
  hint: MessageKey;
  icon: LucideIcon;
  accent: Accent;
  /** Shown locked (its page is disabled) unless the admin has this capability. */
  requires?: keyof Capabilities;
  end?: boolean;
}

export interface NavGroup {
  label: MessageKey;
  items: NavItem[];
}

/** The console's navigation; the topbar breadcrumb uses the group label as the section name. */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "nav.group.operations",
    items: [
      { to: "/", label: "nav.overview", hint: "nav.overview.hint", icon: LayoutDashboard, accent: "green", end: true },
      { to: "/knowledge", label: "nav.knowledge", hint: "nav.knowledge.hint", icon: BookOpen, accent: "blue" },
    ],
  },
  {
    label: "nav.group.support",
    items: [
      { to: "/handoffs", label: "nav.handoffs", hint: "nav.handoffs.hint", icon: Headset, accent: "amber" },
      { to: "/conversations", label: "nav.conversations", hint: "nav.conversations.hint", icon: MessagesSquare, accent: "purple" },
      { to: "/feedback", label: "nav.feedback", hint: "nav.feedback.hint", icon: ThumbsUp, accent: "gold" },
    ],
  },
  {
    label: "nav.group.portal",
    items: [
      { to: "/chat", label: "nav.chat", hint: "nav.chat.hint", icon: MessageSquareQuote, accent: "green" },
      { to: "/widget", label: "nav.widget", hint: "nav.widget.hint", icon: MonitorSmartphone, accent: "blue" },
    ],
  },
  {
    label: "nav.group.system",
    items: [
      { to: "/settings", label: "nav.settings", hint: "nav.settings.hint", icon: Settings, accent: "amber", requires: "isOwner" },
      { to: "/logs", label: "nav.logs", hint: "nav.logs.hint", icon: ScrollText, accent: "purple", requires: "isOwner" },
      { to: "/audit", label: "nav.audit", hint: "nav.audit.hint", icon: FileClock, accent: "gold", requires: "isOwner" },
      { to: "/access", label: "nav.access", hint: "nav.access.hint", icon: ShieldCheck, accent: "red", requires: "isOwner" },
    ],
  },
];

interface SidebarProps {
  capabilities: Capabilities;
  pendingHandoffs: number;
  open: boolean;
  onNavigate: () => void;
  onChangePassword: () => void;
}

export function Sidebar({ capabilities, pendingHandoffs, open, onNavigate, onChangePassword }: SidebarProps) {
  const { t } = useI18n();
  const { admin, signOut } = useSession();
  return (
    <aside className={open ? "sidebar sidebar--open" : "sidebar"} aria-label={t("nav.label")}>
      <div className="sidebar__brand">
        <div className="sidebar__identity">
          <span className="sidebar__logo" aria-hidden>
            <Sparkles size={20} />
          </span>
          <div>
            <div className="sidebar__title">{t("app.title")}</div>
            <div className="sidebar__subtitle">{t("app.subtitle")}</div>
          </div>
        </div>
        <div className="sidebar__pill">
          <Database size={13} aria-hidden />
          {t("app.badge")}
        </div>
      </div>

      <nav className="sidebar__nav">
        {NAV_GROUPS.map((group) => {
          const items = group.items;
          return (
            <div key={group.label}>
              <div className="sidebar__group-label">{t(group.label)}</div>
              <ul className="sidebar__list">
                {items.map(({ to, label, hint, icon: Icon, accent, end, requires }) => {
                  const locked = requires !== undefined && !capabilities[requires];
                  return (
                  <li key={to}>
                    <NavLink to={to} end={end} className={`nav-item nav-item--${accent}${locked ? " nav-item--locked" : ""}`} onClick={onNavigate}>
                      <Icon size={18} aria-hidden />
                      <span className="nav-item__text">
                        <span className="nav-item__label">{t(label)}</span>
                        <span className="nav-item__hint">{t(hint)}</span>
                      </span>
                      {to === "/handoffs" && pendingHandoffs > 0 ? (
                        <span className="nav-item__badge" aria-label={t("nav.pendingCount", { count: pendingHandoffs })}>
                          {pendingHandoffs}
                        </span>
                      ) : locked ? (
                        <Lock size={14} className="nav-item__chevron" aria-label={t("errors.ownerOnly")} />
                      ) : (
                        <ChevronRight size={14} className="nav-item__chevron" aria-hidden />
                      )}
                    </NavLink>
                  </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </nav>

      <div className="sidebar__profile">
        <div className="sidebar__who">
          <span className={`avatar avatar--lg role--${admin.role}`} aria-hidden>
            {admin.email.slice(0, 1)}
          </span>
          <div className="nav-item__text">
            <div className="sidebar__name" title={admin.email}>
              {admin.email}
            </div>
            <span className={`role-chip role--${admin.role}`}>{t(`role.${admin.role}`)}</span>
          </div>
        </div>
        <div className="sidebar__actions">
          <button type="button" className="sidebar__action sidebar__action--grow" onClick={onChangePassword}>
            <KeyRound size={12} aria-hidden />
            {t("account.changePassword")}
          </button>
          <button type="button" className="sidebar__action sidebar__action--danger" onClick={() => void signOut()}>
            <LogOut size={12} aria-hidden />
            {t("account.signOut")}
          </button>
        </div>
        <div className="sidebar__footnote">{t("app.footer")}</div>
      </div>
    </aside>
  );
}
