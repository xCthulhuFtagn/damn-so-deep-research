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
      return <MinusCircle className="w-4 h-4 text-slate-400" />;
    default:
      return (
        <Circle
          className={clsx(
            'w-4 h-4',
            isCurrent ? 'text-primary-500' : 'text-slate-300'
          )}
        />
      );
  }
}

function getStepBgColor(step: PlanStep): string {
  switch (step.status) {
    case 'DONE':
      return 'bg-green-50 border-green-200';
    case 'IN_PROGRESS':
      return 'bg-primary-50 border-primary-200';
    case 'FAILED':
      return 'bg-red-50 border-red-200';
    case 'SKIPPED':
      return 'bg-slate-50 border-slate-200';
    default:
      return 'bg-white border-slate-200';
  }
}

export default function PlanView({ plan, currentStepIndex, phase }: PlanViewProps) {
  const completedCount = plan.filter(
    (s) => s.status === 'DONE' || s.status === 'SKIPPED'
  ).length;

  return (
    <div className="p-4 border-b border-slate-200">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-900">Research Plan</h3>
        <span className="text-xs text-slate-500">
          {completedCount}/{plan.length}
        </span>
      </div>

      {/* Progress bar */}
      <div className="h-1.5 bg-slate-200 rounded-full mb-4">
        <div
          className="h-full bg-primary-500 rounded-full transition-all"
          style={{ width: `${(completedCount / plan.length) * 100}%` }}
        />
      </div>

      {/* Phase indicator */}
      <div className="mb-3 text-xs font-medium text-slate-500 uppercase tracking-wider">
        Phase: {phase}
      </div>

      {/* Steps */}
      <div className="space-y-2 max-h-64 overflow-y-auto">
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
                <p className="font-medium text-slate-900 truncate">
                  {step.description}
                </p>
                {step.result && step.status === 'DONE' && (
                  <p className="mt-1 text-slate-600 line-clamp-2">
                    {step.result.slice(0, 100)}...
                  </p>
                )}
                {step.error && (
                  <p className="mt-1 text-red-600">{step.error}</p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
