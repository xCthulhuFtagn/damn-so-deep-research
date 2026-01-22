import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useResearch } from '../hooks/useResearch';
import { useResearchStore } from '../stores/researchStore';
import Sidebar from './Sidebar/Sidebar';
import ChatContainer from './Chat/ChatContainer';

export default function ResearchPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { fetchRuns, runs, createRun } = useResearchStore();
  const research = useResearch(runId || null);
  const [newRunTitle, setNewRunTitle] = useState('');
  const [showNewRunForm, setShowNewRunForm] = useState(false);

  useEffect(() => {
    fetchRuns();
  }, []);

  const handleCreateRun = async () => {
    if (!newRunTitle.trim()) return;

    try {
      const run = await createRun(newRunTitle);
      setNewRunTitle('');
      setShowNewRunForm(false);
      navigate(`/run/${run.id}`);
    } catch {
      // Error handled by store
    }
  };

  const handleSelectRun = (id: string) => {
    navigate(`/run/${id}`);
  };

  return (
    <div className="flex h-screen bg-slate-50">
      {/* Sidebar */}
      <div className="w-80 border-r border-slate-200 bg-white flex flex-col">
        <div className="p-4 border-b border-slate-200">
          <h1 className="text-lg font-semibold text-slate-900">Deep Research</h1>
          <p className="text-sm text-slate-500">Welcome, {user?.username}</p>
        </div>

        {/* New Run Button/Form */}
        <div className="p-4 border-b border-slate-200">
          {showNewRunForm ? (
            <div className="space-y-2">
              <input
                type="text"
                value={newRunTitle}
                onChange={(e) => setNewRunTitle(e.target.value)}
                placeholder="Research topic..."
                className="w-full px-3 py-2 border border-slate-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                onKeyDown={(e) => e.key === 'Enter' && handleCreateRun()}
              />
              <div className="flex gap-2">
                <button
                  onClick={handleCreateRun}
                  className="flex-1 px-3 py-1.5 bg-primary-600 text-white rounded-md text-sm hover:bg-primary-700"
                >
                  Create
                </button>
                <button
                  onClick={() => setShowNewRunForm(false)}
                  className="px-3 py-1.5 border border-slate-300 rounded-md text-sm hover:bg-slate-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setShowNewRunForm(true)}
              className="w-full px-4 py-2 bg-primary-600 text-white rounded-md hover:bg-primary-700"
            >
              + New Research
            </button>
          )}
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
        <div className="mt-auto p-4 border-t border-slate-200">
          <button
            onClick={logout}
            className="w-full px-4 py-2 text-sm text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-md"
          >
            Sign out
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
        {runId ? (
          <ChatContainer
            messages={research.messages}
            isRunning={research.isRunning}
            phase={research.phase}
            onSendMessage={research.sendMessage}
            onStart={() => research.startResearch()}
            onPause={research.pauseResearch}
            searchThemes={research.searchThemes}
            error={research.error}
            onClearError={research.clearError}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center text-slate-500">
              <p className="text-lg">Select a research run or create a new one</p>
              <p className="text-sm mt-2">
                Start by clicking "New Research" in the sidebar
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
