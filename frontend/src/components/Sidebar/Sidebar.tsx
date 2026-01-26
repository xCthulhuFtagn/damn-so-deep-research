import { Run, PlanStep, Approval } from '../../types';
import RunList from './RunList';
import PlanView from './PlanView';
import ApprovalPanel from './ApprovalPanel';

interface SidebarProps {
  runs: Run[];
  currentRunId?: string;
  onSelectRun: (id: string) => void;
  plan: PlanStep[];
  currentStepIndex: number;
  phase: string;
  pendingApprovals: Approval[];
  onApprove: (hash: string) => void;
  onDeny: (hash: string) => void;
}

export default function Sidebar({
  runs,
  currentRunId,
  onSelectRun,
  plan,
  currentStepIndex,
  phase,
  pendingApprovals,
  onApprove,
  onDeny,
}: SidebarProps) {
  return (
    <div className="flex-1 overflow-y-auto">
      {/* Pending Approvals */}
      {pendingApprovals.length > 0 && (
        <ApprovalPanel
          approvals={pendingApprovals}
          onApprove={onApprove}
          onDeny={onDeny}
        />
      )}

      {/* Current Plan */}
      {plan.length > 0 && (
        <PlanView
          plan={plan}
          currentStepIndex={currentStepIndex}
          phase={phase}
        />
      )}

      {/* Run List */}
      <RunList
        runs={runs}
        currentRunId={currentRunId}
        onSelectRun={onSelectRun}
      />
    </div>
  );
}
