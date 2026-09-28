import Link from "next/link";

/** Landing page of the chat host: points developers to the embed demo and the embed snippet. */
export default function Home() {
  return (
    <main className="mx-auto max-w-2xl space-y-6 px-6 py-16">
      <h1 className="text-2xl font-semibold">Trợ lý ảo</h1>
      <p className="text-slate-600">Máy chủ này phục vụ khung chat nhúng vào website.</p>
      <p>
        <Link href="/embed-demo" className="text-blue-700 underline">
          Trang thử nhúng
        </Link>
        <span className="text-slate-500"> — xem khung chat như trên website.</span>
      </p>
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Mã nhúng</h2>
        <pre className="overflow-x-auto rounded bg-slate-100 p-3 text-sm">
          {`<script src="https://<tên-miền-chatbot>/embed.js" defer data-label="Hỏi đáp"></script>`}
        </pre>
      </section>
    </main>
  );
}
