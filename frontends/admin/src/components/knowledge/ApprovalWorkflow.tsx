import { Archive, CheckCheck, History, Send, XCircle } from "lucide-react";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/vi";
import { Card } from "../ui/primitives";
import { PlannedButton, PlannedSection } from "../ui/Planned";

/** giz-chatbot's document lifecycle; our documents today are only on (in answers) or off. */
const STEPS: MessageKey[] = ["workflow.draft", "workflow.review", "workflow.approved", "workflow.published"];

/** Steps shown as reached: an enabled document already answers questions, i.e. is published. */
export function reachedSteps(enabled: boolean | null): number {
  if (enabled === null) return 0;
  return enabled ? STEPS.length : 1;
}

/** Draft → review → approve → publish steps with their (planned) actions and version history. */
export function ApprovalWorkflow({ enabled }: { enabled: boolean | null }) {
  const { t } = useI18n();
  const reached = reachedSteps(enabled);
  return (
    <Card title={t("workflow.title")}>
      <PlannedSection>
        <ol className="stepper" aria-label={t("workflow.title")}>
          {STEPS.map((step, index) => (
            <li key={step} className={index < reached ? "stepper__step stepper__step--done" : "stepper__step"}>
              <span className="stepper__dot" aria-hidden>
                {index + 1}
              </span>
              {t(step)}
            </li>
          ))}
        </ol>
        <div className="row">
          <PlannedButton small icon={Send} label={t("workflow.submit")} />
          <PlannedButton small icon={CheckCheck} label={t("workflow.approve")} />
          <PlannedButton small icon={XCircle} label={t("workflow.reject")} danger />
          <PlannedButton small icon={Archive} label={t("workflow.archive")} />
          <PlannedButton small icon={History} label={t("workflow.versions")} />
        </div>
      </PlannedSection>
    </Card>
  );
}
