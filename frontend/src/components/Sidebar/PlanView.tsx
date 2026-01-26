import { PlanStep } from '../../types';
import { clsx } from 'clsx';
import { CheckCircle, Circle, AlertCircle, Loader2, MinusCircle } from 'lucide-react';

interface PlanViewProps {
  plan: PlanStep[];
  currentStepIndex: number;
  phase: string;
}

function getStepIcon(step: PlanStep, isCurrent: boolean) {
  switch (step.status) {
    case 'DONE':
      return <CheckCircle className="w-4 h-4 text-green-500" />;
    case 'IN_PROGRESS':
      return <Loader2 className="w-4 h-4 text-primary-500 animate-spin" />;
    case 'FAILED':
      return <AlertCircle className="w-4 h-4 text-red-500" />;
    case 'SKIPPED':
      return <MinusCircle className="w-4 h-4 text-slate-400 dark:text-slate-500" />;
    default:
      return (
        <Circle
          className={clsx(
            'w-4 h-4',
            isCurrent ? 'text-primary-500' : 'text-slate-300 dark:text-slate-600'
          )}
        />
      );
  }
}

function getStepBgColor(step: PlanStep): string {
  switch (step.status) {
    case 'DONE':
      return 'bg-green-50 dark:bg-green-900/10 border-green-200 dark:border-green-800';
    case 'IN_PROGRESS':
      return 'bg-primary-50 dark:bg-primary-900/10 border-primary-200 dark:border-primary-800';
    case 'FAILED':
      return 'bg-red-50 dark:bg-red-900/10 border-red-200 dark:border-red-800';
    case 'SKIPPED':
      return 'bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700';
    default:
      return 'bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-700';
  }
}

export default function PlanView({ plan, currentStepIndex, phase }: PlanViewProps) {
  const completedCount = plan.filter(
    (s) => s.status === 'DONE' || s.status === 'SKIPPED'
  ).length;

  return (
    <div className="p-4 border-b border-slate-200 dark:border-slate-800 flex flex-col min-h-0">
      <div className="flex items-center justify-between mb-3 flex-shrink-0">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Research Plan</h3>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {completedCount}/{plan.length}
        </span>
      </div>

      {/* Progress bar */}
      <div className="h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full mb-4 flex-shrink-0">
        <div
          className="h-full bg-primary-500 rounded-full transition-all"
          style={{ width: `${(completedCount / plan.length) * 100}%` }}
        />
      </div>

      {/* Phase indicator */}
      <div className="mb-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider flex-shrink-0">
        Phase: {phase}
      </div>

      {/* Steps - scrollable area that grows with sidebar */}
      <div className="space-y-2 overflow-y-auto flex-1">
        {plan.map((step, index) => (
          <div
            key={step.id}
            className={clsx(
              'p-2 rounded border text-xs',
              getStepBgColor(step)
            )}
          >
            <div className="flex items-start gap-2">
              {getStepIcon(step, index === currentStepIndex)}
              <div className="flex-1 min-w-0">
                <p className="font-medium text-slate-900 dark:text-slate-100 break-words">
                  {step.description}
                </p>
                {step.result && step.status === 'DONE' && (
                  <p className="mt-1 text-slate-600 dark:text-slate-400 line-clamp-2">
                    {step.result.slice(0, 100)}...
                  </p>
                )}
                {step.error && (
                  <p className="mt-1 text-red-600 dark:text-red-400">{step.error}</p>
                )}
                {/* Substep progress indicator */}
                {(step.status === 'IN_PROGRESS' || step.status === 'FAILED') &&
                  step.substeps &&
                  step.substeps.length > 0 && (
                    <div className="mt-1 flex items-center gap-1">
                      <span className="text-slate-500 dark:text-slate-400">
                        Attempts:
                      </span>
                      {Array.from({ length: step.max_substeps || 3 }).map((_, i) => (
                        <div
                          key={i}
                          className={clsx(
                            'w-2 h-2 rounded-full',
                            i < (step.substeps?.length || 0)
                              ? 'bg-red-400 dark:bg-red-500'
                              : i === (step.current_substep_index || 0)
                              ? 'bg-primary-400 dark:bg-primary-500 animate-pulse'
                              : 'bg-slate-300 dark:bg-slate-600'
                          )}
                        />
                      ))}
                    </div>
                  )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
