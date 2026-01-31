import { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useResearch } from '../hooks/useResearch';
import { useResearchStore } from '../stores/researchStore';
import Sidebar from './Sidebar/Sidebar';
import ChatContainer from './Chat/ChatContainer';
import PlanConfirmationModal from './Chat/PlanConfirmationModal';

const SIDEBAR_WIDTH_KEY = 'research-sidebar-width';
const DEFAULT_SIDEBAR_WIDTH = 320;
const MIN_SIDEBAR_WIDTH = 250;
const MAX_SIDEBAR_WIDTH = 600;

function getSavedWidth(): number {
  try {
    const saved = localStorage.getItem(SIDEBAR_WIDTH_KEY);
    if (saved) {
      const width = parseInt(saved, 10);
      if (width >= MIN_SIDEBAR_WIDTH && width <= MAX_SIDEBAR_WIDTH) {
        return width;
      }
    }
  } catch {
    // Ignore
  }
  return DEFAULT_SIDEBAR_WIDTH;
}

export default function ResearchPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const {
    fetchRuns,
    runs,
    createRun,
    showPlanConfirmationModal,
    confirmPlan,
    rejectPlan,
    closePlanConfirmationModal,
    plan,
    currentRun,
  } = useResearchStore();
  const research = useResearch(runId || null);

  const [sidebarWidth, setSidebarWidth] = useState(getSavedWidth);
  const [isResizing, setIsResizing] = useState(false);

  useEffect(() => {
    fetchRuns();
  }, []);

  const startResizing = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  }, []);

  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      const newWidth = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, e.clientX));
      setSidebarWidth(newWidth);
    };

    const handleMouseUp = () => {
      setIsResizing(false);
      localStorage.setItem(SIDEBAR_WIDTH_KEY, sidebarWidth.toString());
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing, sidebarWidth]);

  const handleCreateRun = async () => {
    const baseName = "New Chat";
    const getNextName = () => {
      const usedNumbers = new Set<number>();
      runs.forEach(r => {
        if (r.title === baseName) usedNumbers.add(1);
        const match = r.title.match(/^New Chat \((\d+)\)$/);
        if (match) usedNumbers.add(parseInt(match[1]));
      });

      if (!usedNumbers.has(1)) return baseName;
      for (let i = 2; ; i++) {
        if (!usedNumbers.has(i)) return `${baseName} (${i})`;
      }
    };

    try {
      const run = await createRun(getNextName());
      navigate(`/run/${run.id}`);
    } catch {
      // Error handled by store
    }
  };

  const handleSelectRun = (id: string) => {
    navigate(`/run/${id}`);
  };

  return (
    <div className="flex h-screen bg-slate-50 dark:bg-slate-950">
      {/* Sidebar */}
      <div
        className="flex-shrink-0 border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex flex-col"
        style={{ width: sidebarWidth }}
      >
        {/* Header */}
        <div className="p-4 border-b border-slate-200 dark:border-slate-800">
          <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Deep Research</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">Welcome, {user?.username}</p>
        </div>

        {/* New Run Button */}
        <div className="p-4 border-b border-slate-200 dark:border-slate-800">
          <button
            onClick={handleCreateRun}
            className="w-full px-4 py-2 bg-primary-600 text-white rounded-md hover:bg-primary-700"
          >
            + New Research
          </button>
        </div>

        {/* Token Counter for current run */}
        {currentRun && (
          <div className="px-4 py-2 border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-500 dark:text-slate-400">Tokens used:</span>
              <span className="font-mono text-slate-700 dark:text-slate-300">
                {currentRun.total_tokens.toLocaleString()}
              </span>
            </div>
          </div>
        )}

        {/* Sidebar Content */}
        <Sidebar
          runs={runs}
          currentRunId={runId}
          onSelectRun={handleSelectRun}
          plan={research.plan}
          currentStepIndex={research.currentStepIndex}
          phase={research.phase}
          pendingApprovals={research.pendingApprovals}
          onApprove={(hash) => research.respondToApproval(hash, true)}
          onDeny={(hash) => research.respondToApproval(hash, false)}
        />

        {/* Logout */}
        <div className="mt-auto p-4 border-t border-slate-200 dark:border-slate-800">
          <button
            onClick={logout}
            className="w-full px-4 py-2 text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-md"
          >
            Sign out
          </button>
        </div>
      </div>

      {/* Resize Handle */}
      <div
        className={`w-1.5 cursor-col-resize flex-shrink-0 transition-colors ${
          isResizing
            ? 'bg-primary-500'
            : 'bg-slate-200 dark:bg-slate-700 hover:bg-primary-400 dark:hover:bg-primary-600'
        }`}
        onMouseDown={startResizing}
      />

      {/* Main Content */}
      <div className={`flex-1 flex flex-col bg-slate-50 dark:bg-slate-950 ${isResizing ? 'select-none' : ''}`}>
        {runId ? (
          <ChatContainer
            messages={research.messages}
            isRunning={research.isRunning}
            phase={research.phase}
            currentRun={research.currentRun}
            onSendMessage={research.sendMessage}
            onPause={research.pauseResearch}
            onResume={research.resumeResearch}
            searchThemes={research.searchThemes}
            error={research.error}
            onClearError={research.clearError}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center text-slate-500 dark:text-slate-400">
              <p className="text-lg">Select a research run or create a new one</p>
              <p className="text-sm mt-2">
                Start by clicking "New Research" in the sidebar
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Plan Confirmation Modal */}
      {showPlanConfirmationModal && (
        <PlanConfirmationModal
          plan={plan}
          onConfirm={confirmPlan}
          onReject={rejectPlan}
          onCancel={closePlanConfirmationModal}
        />
      )}
    </div>
  );
}
