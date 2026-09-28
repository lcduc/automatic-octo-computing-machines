import type { Metadata } from "next";
import Script from "next/script";

export const metadata: Metadata = { title: "Thử nhúng", robots: { index: false, follow: false } };

/** A stand-in host page that loads embed.js exactly like the real website would. */
export default function EmbedDemoPage() {
  return (
    <main className="mx-auto max-w-3xl space-y-4 px-6 py-12">
      <h1 className="text-2xl font-semibold">Trang thử nhúng khung chat</h1>
      <p className="text-slate-600">
        Trang này mô phỏng một trang của website. Nút &quot;Hỏi đáp&quot; ở góc phải bên dưới được tạo bởi
        <code className="mx-1 rounded bg-slate-100 px-1">embed.js</code>, giống hệt khi nhúng vào website thật.
      </p>
      <Script src="/embed.js" strategy="afterInteractive" data-label="Hỏi đáp" />
    </main>
  );
}
