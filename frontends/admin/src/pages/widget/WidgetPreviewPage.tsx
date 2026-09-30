import { Check, Copy, Monitor, RefreshCw, Smartphone, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { Callout, Card, ErrorState, LoadingState, PageHeader } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { Settings } from "../../lib/types";
import { useApi } from "../../lib/use-api";
import { useWidgetOrigin } from "./use-widget-origin";

type Device = "desktop" | "mobile";
/** How long the "copied" tick stays visible. */
const COPIED_MS = 2000;

/** The embed snippet a client pastes into their site (same attributes embed.js reads). */
export function embedSnippet(origin: string, color: string, label: string): string {
  return `<script src="${origin}/embed.js" defer\n        data-color="${color}" data-position="right" data-label="${label}"></script>`;
}

/**
 * The real chat widget, framed the way embed.js frames it on a client's site,
 * inside a stand-in host page. This page answers the widget's handshake as an
 * anonymous host (`host:hello`), so the preview never waits for a sign-in.
 */
export function WidgetPreviewPage() {
  const { t } = useI18n();
  const origin = useWidgetOrigin();
  const settings = useApi<Settings>("settings");
  const [device, setDevice] = useState<Device>("desktop");
  const [open, setOpen] = useState(true);
  const [frameKey, setFrameKey] = useState(0);
  const [copied, setCopied] = useState(false);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const color = settings.data?.widget_primary_color ?? "#0a2540";
  const label = settings.data?.widget_title ?? t("nav.widget");

  // The CSP forbids style attributes; a custom property set through the CSSOM is allowed.
  const stageRef = useCallback((node: HTMLDivElement | null) => node?.style.setProperty("--brand", color), [color]);

  useEffect(() => {
    if (!origin.value) return;
    const widgetOrigin = origin.value;
    const onMessage = (event: MessageEvent) => {
      const frame = frameRef.current?.contentWindow;
      if (event.origin !== widgetOrigin || !frame || event.source !== frame) return;
      const type = (event.data as { type?: unknown } | null)?.type;
      if (type === "chatbot:ready" || type === "chatbot:request_token") frame.postMessage({ type: "host:hello" }, widgetOrigin);
      else if (type === "chatbot:close") setOpen(false);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [origin.value]);

  const copySnippet = async () => {
    if (!origin.value) return;
    try {
      await navigator.clipboard.writeText(embedSnippet(origin.value, color, label));
      setCopied(true);
      window.setTimeout(() => setCopied(false), COPIED_MS);
    } catch {
      // Clipboard blocked: the snippet stays selectable on screen.
    }
  };

  return (
    <>
      <PageHeader
        title={t("nav.widget")}
        description={t("widgetPreview.description")}
        actions={
          <>
            <div className="lang-toggle" role="group" aria-label={t("widgetPreview.device")}>
              <button type="button" aria-pressed={device === "desktop"} onClick={() => setDevice("desktop")}>
                <Monitor size={13} aria-hidden /> {t("widgetPreview.desktop")}
              </button>
              <button type="button" aria-pressed={device === "mobile"} onClick={() => setDevice("mobile")}>
                <Smartphone size={13} aria-hidden /> {t("widgetPreview.mobile")}
              </button>
            </div>
            <button type="button" className="btn btn--sm" onClick={() => setFrameKey((value) => value + 1)} disabled={!origin.value}>
              <RefreshCw size={14} aria-hidden />
              {t("widgetPreview.reload")}
            </button>
            <Link to="/settings?tab=widget" className="btn btn--sm">
              {t("widgetPreview.customise")}
            </Link>
          </>
        }
      />

      {origin.error && <ErrorState message={origin.error} onRetry={origin.reload} />}
      {origin.loading && <LoadingState />}
      {!origin.loading && !origin.error && !origin.value && <Callout tone="warning">{t("widgetPreview.notConfigured")}</Callout>}

      {origin.value && (
        <>
          <div ref={stageRef} className={`widget-stage widget-stage--${device}`}>
            <div className="widget-stage__site" aria-hidden>
              <div className="widget-stage__bar" />
              <div className="widget-stage__hero" />
              <div className="widget-stage__line" />
              <div className="widget-stage__line widget-stage__line--short" />
              <div className="widget-stage__line" />
            </div>
            <div className="widget-stage__panel" hidden={!open}>
              {/* Cross-origin frame: scripts + same-origin keep the widget working and still cannot reach this page. */}
              <iframe
                key={frameKey}
                ref={frameRef}
                src={`${origin.value}/widget`}
                title={label}
                allow="clipboard-write"
                // oxlint-disable-next-line react/iframe-missing-sandbox
                sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox"
                className="widget-stage__frame"
              />
            </div>
            <button type="button" className="widget-stage__launcher" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
              {open ? <X size={16} aria-hidden /> : null}
              {open ? t("common.close") : label}
            </button>
          </div>

          <Callout>{t("widgetPreview.framingHint", { admin: window.location.origin })}</Callout>

          <Card
            title={t("widgetPreview.snippet")}
            actions={
              <button type="button" className="btn btn--sm" onClick={() => void copySnippet()}>
                {copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
                {copied ? t("chat.copied") : t("chat.copy")}
              </button>
            }
          >
            <p className="small muted">{t("widgetPreview.snippetHint")}</p>
            <pre className="json mt-3">{embedSnippet(origin.value, color, label)}</pre>
          </Card>
        </>
      )}
    </>
  );
}
