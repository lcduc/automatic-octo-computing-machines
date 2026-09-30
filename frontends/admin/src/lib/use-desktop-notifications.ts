import { useCallback, useEffect, useRef, useState } from "react";

export type NotificationState = "unsupported" | NotificationPermission;

function currentState(): NotificationState {
  return typeof window !== "undefined" && "Notification" in window ? Notification.permission : "unsupported";
}

/** Whether a count change deserves a desktop notification (it grew after the first load). */
export function shouldNotify(previous: number | null, next: number): boolean {
  return previous !== null && next > previous;
}

/**
 * Browser notifications when the number of waiting handoffs grows, so staff on
 * another tab see new requests. Opt-in: nothing is shown until the admin allows it.
 *
 * @param pending - Current count of open handoffs, or null while unknown.
 * @param message - Title and body for a notification about `pending` requests.
 */
export function useDesktopNotifications(pending: number | null, message: (count: number) => { title: string; body: string }) {
  const [state, setState] = useState<NotificationState>(currentState);
  const previous = useRef<number | null>(null);

  useEffect(() => {
    if (pending === null) return;
    if (state === "granted" && shouldNotify(previous.current, pending)) {
      const { title, body } = message(pending);
      try {
        const notification = new Notification(title, { body, tag: "admin-handoffs" });
        notification.onclick = () => window.focus();
      } catch {
        // Some browsers only allow notifications from a service worker; the bell still shows the count.
      }
    }
    previous.current = pending;
  }, [pending, state, message]);

  const enable = useCallback(async () => {
    if (state === "unsupported") return;
    setState(await Notification.requestPermission());
  }, [state]);

  return { state, enable };
}
