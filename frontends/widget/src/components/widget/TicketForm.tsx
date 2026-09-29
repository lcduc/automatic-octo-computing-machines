"use client";

import { useState, type FormEvent } from "react";

export interface TicketContact {
  name?: string;
  email?: string;
  phone?: string;
  details?: string;
  consent: boolean;
}

interface TicketFormProps {
  /** Signed-in users are answered in the chat; contact details are optional for them. */
  signedIn: boolean;
  /** When staff are expected to answer (ISO time), shown to the visitor (HND-14). */
  replyBy?: string;
  onSubmit: (contact: TicketContact) => Promise<string | null>;
}

function formatReplyBy(iso?: string): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleString("vi-VN", { weekday: "long", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** Contact details for a support ticket, with the consent notice the law requires (HND-13, PRV-02). */
export function TicketForm({ signedIn, replyBy, onSubmit }: TicketFormProps) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [details, setDetails] = useState("");
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const due = formatReplyBy(replyBy);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!signedIn && !email.trim() && !phone.trim()) return setError("Vui lòng để lại e-mail hoặc số điện thoại để chúng tôi phản hồi.");
    if ((email.trim() || phone.trim()) && !consent) return setError("Vui lòng đồng ý với cách chúng tôi dùng thông tin liên hệ.");
    const problem = await onSubmit({ name, email, phone, details, consent });
    if (problem) return setError(problem);
    setSent(true);
  };

  if (sent) {
    return (
      <p className="max-w-[92%] rounded border border-emerald-300 bg-emerald-50 px-2 py-1 text-xs text-emerald-900" role="status">
        Đã ghi nhận. {due ? `Nhân viên sẽ phản hồi trước ${due}` : "Nhân viên sẽ phản hồi sớm nhất có thể"}
        {signedIn ? ", ngay trong khung trò chuyện này." : "."}
      </p>
    );
  }

  return (
    <form onSubmit={submit} className="w-full max-w-[92%] space-y-1.5 rounded border border-amber-300 bg-amber-50 p-2 text-xs text-slate-800">
      <p className="font-semibold">
        {due ? `Nhân viên sẽ phản hồi trước ${due}.` : "Nhân viên sẽ phản hồi sớm nhất có thể."}{" "}
        {signedIn ? "Câu trả lời sẽ hiện ở đây; bạn có thể để lại e-mail để nhận thêm qua thư." : "Để lại cách liên hệ để nhận câu trả lời:"}
      </p>
      <label className="block">
        <span className="sr-only">Họ tên</span>
        <input className="w-full rounded border border-slate-300 px-2 py-1" placeholder="Họ tên (không bắt buộc)" maxLength={128} value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="block">
        <span className="sr-only">E-mail</span>
        <input className="w-full rounded border border-slate-300 px-2 py-1" type="email" placeholder="E-mail" maxLength={255} value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label className="block">
        <span className="sr-only">Số điện thoại</span>
        <input className="w-full rounded border border-slate-300 px-2 py-1" type="tel" placeholder="Số điện thoại" maxLength={32} value={phone} onChange={(e) => setPhone(e.target.value)} />
      </label>
      <label className="block">
        <span className="sr-only">Nội dung cần hỗ trợ</span>
        <textarea className="w-full rounded border border-slate-300 px-2 py-1" rows={2} placeholder="Bạn cần hỗ trợ gì? (không bắt buộc)" maxLength={2000} value={details} onChange={(e) => setDetails(e.target.value)} />
      </label>
      <label className="flex items-start gap-1.5">
        <input type="checkbox" className="mt-0.5" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        <span>
          Tôi đồng ý để thông tin liên hệ này được lưu và chỉ dùng để phản hồi yêu cầu hỗ trợ; nó được xoá theo thời hạn lưu trữ
          của chúng tôi hoặc khi tôi yêu cầu.
        </span>
      </label>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      <button type="submit" className="rounded bg-[var(--brand)] px-3 py-1 font-semibold text-white">Gửi yêu cầu</button>
    </form>
  );
}
