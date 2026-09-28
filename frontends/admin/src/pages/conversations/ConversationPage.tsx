import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router";
import { Transcript } from "../../components/conversations/Transcript";
import { Card, ErrorState, LoadingState, PageHeader } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { ConversationDetail } from "../../lib/types";
import { useApi } from "../../lib/use-api";

export function ConversationPage() {
  const { t, formatDateTime } = useI18n();
  const { id } = useParams();
  const { data, error, reload } = useApi<ConversationDetail>(id ? `conversations/${id}` : null);

  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <LoadingState />;

  return (
    <>
      <Link to="/conversations" className="row small">
        <ArrowLeft size={14} aria-hidden />
        {t("conversations.back")}
      </Link>
      <PageHeader
        title={t("conversations.detailTitle", { visitor: data.end_user_id })}
        description={t("conversations.detailMeta", { channel: data.channel, started: formatDateTime(data.created_at), count: data.message_count })}
      />
      <Card>
        <Transcript messages={data.messages} />
      </Card>
    </>
  );
}
