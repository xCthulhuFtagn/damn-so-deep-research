import { useState } from 'react';
import { PlanStep } from '../../types';
import { X, CheckCircle, XCircle, ListChecks } from 'lucide-react';

interface PlanConfirmationModalProps {
  plan: PlanStep[];
  onConfirm: (feedback?: string) => void;
  onReject: (feedback: string) => void;
  onCancel: () => void;
}

export default function PlanConfirmationModal({
  plan,
  onConfirm,
  onReject,
  onCancel,
}: PlanConfirmationModalProps) {
  const [feedback, setFeedback] = useState('');

  const handleConfirm = () => {
    onConfirm(feedback.trim() || undefined);
  };

  const handleReject = () => {
    if (!feedback.trim()) {
      // Focus on feedback textarea if rejecting without feedback
      return;
    }
    onReject(feedback.trim());
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50"
        onClick={onCancel}
      />

      {/* Modal */}
      <div className="relative bg-white dark:bg-slate-900 rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-3">
            <ListChecks className="w-5 h-5 text-primary-600 dark:text-primary-400" />
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              Research Plan Ready
            </h2>
          </div>
          <button
            onClick={onCancel}
            className="p-1 hover:bg-slate-100 dark:hover:bg-slate-800 rounded"
          >
            <X className="w-5 h-5 text-slate-500 dark:text-slate-400" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
            Review the research plan below. You can approve it to proceed, or provide feedback to request changes.
          </p>

          <div className="space-y-3 mb-6">
            {plan.map((step, index) => (
              <div
                key={step.id}
                className="flex items-start gap-3 p-3 bg-slate-50 dark:bg-slate-800 rounded-lg"
              >
                <span className="flex-shrink-0 w-6 h-6 flex items-center justify-center bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300 rounded-full text-sm font-medium">
                  {index + 1}
                </span>
                <p className="text-sm text-slate-700 dark:text-slate-300">
                  {step.description}
                </p>
              </div>
            ))}
          </div>

          {/* Feedback Input */}
          <div>
            <label
              htmlFor="plan-feedback"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
            >
              Feedback (optional for approval, required for rejection)
            </label>
            <textarea
              id="plan-feedback"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="Add any comments or requested changes to the plan..."
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 resize-none"
              rows={3}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-slate-200 dark:border-slate-700">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-md"
          >
            Cancel
          </button>
          <div className="flex items-center gap-3">
            <button
              onClick={handleReject}
              disabled={!feedback.trim()}
              className="flex items-center gap-2 px-4 py-2 text-sm bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 rounded-md hover:bg-red-200 dark:hover:bg-red-900/50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <XCircle className="w-4 h-4" />
              Request Changes
            </button>
            <button
              onClick={handleConfirm}
              className="flex items-center gap-2 px-4 py-2 text-sm bg-primary-600 text-white rounded-md hover:bg-primary-700"
            >
              <CheckCircle className="w-4 h-4" />
              Approve Plan
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
