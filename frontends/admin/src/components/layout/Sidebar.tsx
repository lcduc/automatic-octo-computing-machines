import {
  BookOpen,
  Bot,
  FileClock,
  Headset,
  LayoutDashboard,
  MessagesSquare,
  ScrollText,
  Settings,
  ShieldCheck,
  ThumbsUp,
  type LucideIcon,
} from "lucide-react";
import { NavLink } from "react-router";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/vi";
import type { Capabilities } from "../../lib/permissions";

interface NavItem {
  to: string;
  label: MessageKey;
  icon: LucideIcon;
  /** Hidden unless the admin has this capability. */
  requires?: keyof Capabilities;
  end?: boolean;
}

const GROUPS: Array<{ label: MessageKey; items: NavItem[] }> = [
  {
    label: "nav.group.operations",
    items: [
      { to: "/", label: "nav.overview", icon: LayoutDashboard, end: true },
      { to: "/conversations", label: "nav.conversations", icon: MessagesSquare },
      { to: "/handoffs", label: "nav.handoffs", icon: Headset },
      { to: "/feedback", label: "nav.feedback", icon: ThumbsUp },
    ],
  },
  {
    label: "nav.group.knowledge",
    items: [{ to: "/knowledge", label: "nav.knowledge", icon: BookOpen }],
  },
  {
    label: "nav.group.system",
    items: [
      { to: "/settings", label: "nav.settings", icon: Settings },
      { to: "/logs", label: "nav.logs", icon: ScrollText },
      { to: "/access", label: "nav.access", icon: ShieldCheck, requires: "isOwner" },
      { to: "/audit", label: "nav.audit", icon: FileClock, requires: "isOwner" },
    ],
  },
];

interface SidebarProps {
  capabilities: Capabilities;
  pendingHandoffs: number;
  open: boolean;
  onNavigate: () => void;
}

export function Sidebar({ capabilities, pendingHandoffs, open, onNavigate }: SidebarProps) {
  const { t } = useI18n();
  return (
    <aside className={open ? "sidebar sidebar--open" : "sidebar"} aria-label={t("nav.label")}>
      <div className="sidebar__brand">
        <span className="sidebar__logo" aria-hidden>
          <Bot size={20} />
        </span>
        <div>
          <div className="sidebar__title">{t("app.title")}</div>
          <div className="sidebar__subtitle">{t("app.subtitle")}</div>
        </div>
      </div>
      <nav className="sidebar__nav">
        {GROUPS.map((group) => {
          const items = group.items.filter((item) => !item.requires || capabilities[item.requires]);
          if (!items.length) return null;
          return (
            <div key={group.label}>
              <div className="sidebar__group-label">{t(group.label)}</div>
              <ul className="sidebar__list">
                {items.map(({ to, label, icon: Icon, end }) => (
                  <li key={to}>
                    <NavLink to={to} end={end} className="nav-item" onClick={onNavigate}>
                      <Icon size={17} aria-hidden />
                      {t(label)}
                      {to === "/handoffs" && pendingHandoffs > 0 && (
                        <span className="nav-item__badge" aria-label={t("nav.pendingCount", { count: pendingHandoffs })}>
                          {pendingHandoffs}
                        </span>
                      )}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </nav>
      <div className="sidebar__footer">{t("app.footer")}</div>
    </aside>
  );
}
