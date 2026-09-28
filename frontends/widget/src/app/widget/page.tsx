import type { Metadata } from "next";
import { connection } from "next/server";
import { ChatWidget } from "@/components/widget/ChatWidget";
import { widgetAllowedParents } from "@/lib/server/config";

export const metadata: Metadata = {
  title: "Trợ lý ảo",
  robots: { index: false, follow: false },
};

/**
 * The chat UI loaded inside the iframe that embed.js places on host pages.
 * Rendered per request so the allowed host origins come from the runtime environment.
 */
export default async function WidgetPage() {
  await connection();
  return <ChatWidget allowedOrigins={widgetAllowedParents()} />;
}
