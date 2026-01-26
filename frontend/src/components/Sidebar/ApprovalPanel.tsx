import { Approval } from '../../types';
import { AlertTriangle, Check, X } from 'lucide-react';

interface ApprovalPanelProps {
  approvals: Approval[];
  onApprove: (hash: string) => void;
  onDeny: (hash: string) => void;
}

export default function ApprovalPanel({
  approvals,
  onApprove,
  onDeny,
}: ApprovalPanelProps) {
  return (
    <div className="p-4 border-b border-slate-200 dark:border-slate-800 bg-yellow-50 dark:bg-yellow-900/10">
      <div className="flex items-center gap-2 mb-3">
        <AlertTriangle className="w-4 h-4 text-yellow-600 dark:text-yellow-500" />
        <h3 className="text-sm font-semibold text-yellow-800 dark:text-yellow-200">
          Pending Approvals ({approvals.length})
        </h3>
      </div>

      <div className="space-y-3">
        {approvals.map((approval) => (
          <div
            key={approval.command_hash}
            className="p-3 bg-white dark:bg-slate-900 rounded-md border border-yellow-200 dark:border-yellow-800"
          >
            <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">Command to execute:</p>
            <code className="block text-sm bg-slate-100 dark:bg-slate-800 p-2 rounded font-mono text-slate-800 dark:text-slate-200 overflow-x-auto">
              {approval.command_text}
            </code>
            <div className="flex gap-2 mt-3">
              <button
                onClick={() => onApprove(approval.command_hash)}
                className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 bg-green-600 text-white rounded text-sm hover:bg-green-700"
              >
                <Check className="w-4 h-4" />
                Approve
              </button>
              <button
                onClick={() => onDeny(approval.command_hash)}
                className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 bg-red-600 text-white rounded text-sm hover:bg-red-700"
              >
                <X className="w-4 h-4" />
                Deny
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
