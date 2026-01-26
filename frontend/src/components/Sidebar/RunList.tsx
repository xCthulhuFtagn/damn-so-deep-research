import { Run } from '../../types';
import { clsx } from 'clsx';

interface RunListProps {
  runs: Run[];
  currentRunId?: string;
  onSelectRun: (id: string) => void;
}

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getStatusColor(status: Run['status']): string {
  switch (status) {
    case 'active':
      return 'bg-green-500';
    case 'paused':
      return 'bg-yellow-500';
    case 'completed':
      return 'bg-blue-500';
    case 'failed':
      return 'bg-red-500';
    default:
      return 'bg-slate-400';
  }
}

export default function RunList({ runs, currentRunId, onSelectRun }: RunListProps) {
  if (runs.length === 0) {
    return (
      <div className="p-4 text-center text-slate-500 dark:text-slate-400 text-sm">
        No research runs yet
      </div>
    );
  }

  return (
    <div className="p-2">
      <h3 className="px-2 py-1 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
        Recent Runs
      </h3>
      <div className="space-y-1 mt-2">
        {runs.map((run) => (
          <button
            key={run.id}
            onClick={() => onSelectRun(run.id)}
            className={clsx(
              'w-full text-left px-3 py-2 rounded-md transition-colors',
              currentRunId === run.id
                ? 'bg-primary-50 dark:bg-primary-900/20 border border-primary-200 dark:border-primary-800'
                : 'hover:bg-slate-100 dark:hover:bg-slate-800'
            )}
          >
            <div className="flex items-center gap-2">
              <span
                className={clsx('w-2 h-2 rounded-full', getStatusColor(run.status))}
              />
              <span className="flex-1 text-sm font-medium text-slate-900 dark:text-slate-100 truncate">
                {run.title}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
              <span>{formatDate(run.created_at)}</span>
              <span>•</span>
              <span>{run.total_tokens.toLocaleString()} tokens</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
