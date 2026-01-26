import { useCallback, useEffect } from 'react';
import { useResearchStore } from '../stores/researchStore';
import { useWebSocket } from './useWebSocket';

export function useResearch(runId: string | null) {
  const store = useResearchStore();

  // Handle WebSocket events
  const handleWSEvent = useCallback(
    (event: Parameters<typeof store.handleWSEvent>[0]) => {
      store.handleWSEvent(event);
    },
    [store]
  );

  // Connect WebSocket
  useWebSocket(runId, handleWSEvent);

  // Load run when selected
  useEffect(() => {
    if (runId) {
      store.selectRun(runId);
    }
  }, [runId]);

  return {
    // State
    currentRun: store.currentRun,
    phase: store.phase,
    plan: store.plan,
    currentStepIndex: store.currentStepIndex,
    messages: store.messages,
    isRunning: store.isRunning,
    searchThemes: store.searchThemes,
    pendingApprovals: store.pendingApprovals,
    isLoading: store.isLoading,
    error: store.error,

    // Actions
    startResearch: store.startResearch,
    pauseResearch: store.pauseResearch,
    sendMessage: store.sendMessage,
    respondToApproval: store.respondToApproval,
    clearError: store.clearError,
  };
}
