import type { Metadata } from "next";
import { ChatWidget } from "@/components/widget/ChatWidget";

export const metadata: Metadata = {
  title: "Trợ lý ảo",
  robots: { index: false, follow: false },
};

/** The chat UI loaded inside the iframe that embed.js places on host pages. */
export default function WidgetPage() {
  return <ChatWidget />;
}
