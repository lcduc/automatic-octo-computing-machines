import { BookOpen, ChevronDown, ChevronUp, ExternalLink } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Spinner } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { Citation, DocumentDetail } from "../../lib/types";
import { useApi } from "../../lib/use-api";

/** The cited passage, loaded from the knowledge base only when the card is opened. */
function CitedPassage({ citation }: { citation: Citation }) {
  const { t } = useI18n();
  const { data, error } = useApi<DocumentDetail>(`knowledge/documents/${citation.document_id}`);
  if (error) return <p className="small muted">{error}</p>;
  if (!data) return <Spinner />;
  const chunk = data.chunks.find((item) => item.id === citation.chunk_id);
  return <blockquote className="citation__quote">{chunk ? chunk.content : t("chat.citationGone")}</blockquote>;
}

export function CitationCard({ citation }: { citation: Citation }) {
  const { t, formatNumber } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <div className="citation">
      <button type="button" className="citation__head" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <BookOpen size={16} aria-hidden />
        <span className="citation__title">
          <strong>{citation.title}</strong>
          <span className="small muted">
            {[citation.section, citation.source].filter(Boolean).join(" · ")}
          </span>
        </span>
        <span className="citation__score">{t("chat.match", { score: formatNumber(citation.score * 100, 0) })}</span>
        {open ? <ChevronUp size={14} aria-hidden /> : <ChevronDown size={14} aria-hidden />}
      </button>
      {open && (
        <div className="citation__body">
          <CitedPassage citation={citation} />
          <div className="row small">
            <Link to={`/knowledge/${citation.document_id}`}>{t("chat.openDocument")}</Link>
            {citation.url && (
              <a href={citation.url} target="_blank" rel="noopener noreferrer nofollow" className="row">
                <ExternalLink size={12} aria-hidden />
                {t("chat.openSource")}
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
