import { Lock } from "lucide-react";
import { useLocation } from "react-router";
import { NAV_GROUPS } from "../layout/Sidebar";
import { useI18n } from "../../i18n/I18nProvider";

/** Placeholder rows drawn behind the lock so the page reads as "there, but out of reach". */
const GHOST_ROWS = 6;

/**
 * Covers a page the signed-in role may not open. The real page is not rendered
 * (the backend would refuse its calls anyway) and takes the colour of its sidebar tab; blurred placeholder cards stand in
 * for it while the navigation around it stays usable.
 */
export function LockedScreen() {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const accent = NAV_GROUPS.flatMap((group) => group.items).find((item) => item.to === pathname)?.accent;
  return (
    <div className={`locked-screen${accent ? ` nav-item--${accent}` : ""}`} role="alert">
      <div className="locked-screen__ghost" aria-hidden>
        {Array.from({ length: GHOST_ROWS }, (_, index) => (
          <div key={index} className="locked-screen__ghost-card skeleton" />
        ))}
      </div>
      <div className="locked-screen__panel">
        <span className="locked-screen__icon">
          <Lock size={32} aria-hidden />
        </span>
        <h2>{t("errors.restrictedTitle")}</h2>
        <p>{t("errors.ownerOnly")}</p>
      </div>
    </div>
  );
}
