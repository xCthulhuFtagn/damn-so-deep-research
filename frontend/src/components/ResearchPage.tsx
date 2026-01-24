import { useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useResearch } from '../hooks/useResearch';
import { useResearchStore } from '../stores/researchStore';
import Sidebar from './Sidebar/Sidebar';
import ChatContainer from './Chat/ChatContainer';
import PlanConfirmationModal from './Chat/PlanConfirmationModal';

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
  } = useResearchStore();
  const research = useResearch(runId || null);

  useEffect(() => {
    fetchRuns();
  }, []);

  const handleCreateRun = async () => {
    // Generate default name with sequential counter (gaps filled)
    const baseName = "New Chat";
    const getNextName = () => {
      // Find all existing "New Chat" and "New Chat (N)" names
      const usedNumbers = new Set<number>();
      runs.forEach(r => {
        if (r.title === baseName) usedNumbers.add(1);
        const match = r.title.match(/^New Chat \((\d+)\)$/);
        if (match) usedNumbers.add(parseInt(match[1]));
      });

      // Find first available number
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
      <div className="w-80 border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex flex-col">
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

      {/* Main Content */}
      <div className="flex-1 flex flex-col bg-slate-50 dark:bg-slate-950">
        {runId ? (
          <ChatContainer
            messages={research.messages}
            isRunning={research.isRunning}
            phase={research.phase}
            onSendMessage={research.sendMessage}
            onPause={research.pauseResearch}
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
