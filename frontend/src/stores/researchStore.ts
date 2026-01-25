import { create } from 'zustand';
import { Message, PlanStep, Run, Approval, WSEvent } from '../types';
import { runsApi, researchApi, approvalsApi } from '../api/client';

interface ResearchState {
  // Current run
  currentRun: Run | null;
  runs: Run[];

  // Research state
  phase: string;
  plan: PlanStep[];
  currentStepIndex: number;
  messages: Message[];
  isRunning: boolean;

  // Parallel search
  searchThemes: string[];

  // Approvals
  pendingApprovals: Approval[];

  // UI state
  isLoading: boolean;
  error: string | null;
  showPlanConfirmationModal: boolean;

  // Actions - Runs
  fetchRuns: () => Promise<void>;
  createRun: (title: string) => Promise<Run>;
  selectRun: (runId: string) => Promise<void>;
  deleteRun: (runId: string) => Promise<void>;
  updateRunTitle: (runId: string, title: string) => Promise<void>;

  // Actions - Research
  startResearch: (message?: string) => Promise<void>;
  pauseResearch: () => Promise<void>;
  sendMessage: (message: string) => Promise<void>;
  fetchState: () => Promise<void>;

  // Actions - Approvals
  fetchApprovals: () => Promise<void>;
  respondToApproval: (commandHash: string, approved: boolean) => Promise<void>;

  // Actions - WebSocket events
  handleWSEvent: (event: WSEvent) => void;

  // Actions - UI
  addMessage: (message: Message) => void;
  updatePlan: (plan: PlanStep[]) => void;
  setPhase: (phase: string) => void;
  clearError: () => void;
  reset: () => void;

  // Actions - Plan Confirmation
  confirmPlan: (feedback?: string) => Promise<void>;
  rejectPlan: (feedback: string) => Promise<void>;
  closePlanConfirmationModal: () => void;
}

export const useResearchStore = create<ResearchState>((set, get) => ({
  currentRun: null,
  runs: [],
  phase: 'idle',
  plan: [],
  currentStepIndex: 0,
  messages: [],
  isRunning: false,
  searchThemes: [],
  pendingApprovals: [],
  isLoading: false,
  error: null,
  showPlanConfirmationModal: false,

  // Runs
  fetchRuns: async () => {
    set({ isLoading: true });
    try {
      const response = await runsApi.list();
      set({ runs: response.runs, isLoading: false });
    } catch (error) {
      set({ error: 'Failed to fetch runs', isLoading: false });
    }
  },

  createRun: async (title: string) => {
    set({ isLoading: true });
    try {
      const run = await runsApi.create(title);
      set((state) => ({
        runs: [run, ...state.runs],
        currentRun: run,
        isLoading: false,
        // Reset research state for new run
        phase: 'idle',
        plan: [],
        messages: [],
        currentStepIndex: 0,
      }));
      return run;
    } catch (error) {
      set({ error: 'Failed to create run', isLoading: false });
      throw error;
    }
  },

  selectRun: async (runId: string) => {
    set({ isLoading: true });
    try {
      const run = await runsApi.get(runId);
      const state = await researchApi.getState(runId);

      set({
        currentRun: run,
        phase: state.phase || 'idle',
        plan: state.plan || [],
        currentStepIndex: state.current_step_index || 0,
        messages: state.messages || [],
        isRunning: state.is_running || false,
        isLoading: false,
      });
    } catch (error) {
      set({ error: 'Failed to load run', isLoading: false });
    }
  },

  deleteRun: async (runId: string) => {
    try {
      await runsApi.delete(runId);
      set((state) => ({
        runs: state.runs.filter((r) => r.id !== runId),
        currentRun: state.currentRun?.id === runId ? null : state.currentRun,
      }));
    } catch (error) {
      set({ error: 'Failed to delete run' });
    }
  },

  updateRunTitle: async (runId: string, title: string) => {
    try {
      await runsApi.update(runId, { title });
      set((state) => ({
        runs: state.runs.map((r) =>
          r.id === runId ? { ...r, title } : r
        ),
        currentRun:
          state.currentRun?.id === runId
            ? { ...state.currentRun, title }
            : state.currentRun,
      }));
    } catch (error) {
      console.error('Failed to update run title:', error);
    }
  },

  // Research
  startResearch: async (message?: string) => {
    const { currentRun } = get();
    if (!currentRun) return;

    set({ isLoading: true, isRunning: true });
    try {
      await researchApi.start(currentRun.id, message);
      set({ isLoading: false });
    } catch (error) {
      set({ error: 'Failed to start research', isLoading: false, isRunning: false });
    }
  },

  pauseResearch: async () => {
    const { currentRun } = get();
    if (!currentRun) return;

    try {
      await researchApi.pause(currentRun.id);
      set({ isRunning: false, phase: 'paused' });
    } catch (error) {
      set({ error: 'Failed to pause research' });
    }
  },

  sendMessage: async (message: string) => {
    const { currentRun, messages, updateRunTitle } = get();
    if (!currentRun) return;

    // Check if this is the first message (no existing messages)
    const isFirstMessage = messages.length === 0;

    // Add user message immediately
    set((state) => ({
      messages: [...state.messages, { role: 'user', content: message }],
      isRunning: true,
    }));

    try {
      // If first message, update the run title to the query
      if (isFirstMessage) {
        // Truncate long queries for the title
        const title = message.length > 100 ? message.substring(0, 97) + '...' : message;
        await updateRunTitle(currentRun.id, title);
      }

      await researchApi.sendMessage(currentRun.id, message);
    } catch (error) {
      set({ error: 'Failed to send message', isRunning: false });
    }
  },

  fetchState: async () => {
    const { currentRun } = get();
    if (!currentRun) return;

    try {
      const state = await researchApi.getState(currentRun.id);
      set({
        phase: state.phase,
        plan: state.plan,
        currentStepIndex: state.current_step_index,
        messages: state.messages,
        isRunning: state.is_running,
      });
    } catch (error) {
      console.error('Failed to fetch state:', error);
    }
  },

  // Approvals
  fetchApprovals: async () => {
    const { currentRun } = get();
    if (!currentRun) return;

    try {
      const response = await approvalsApi.getPending(currentRun.id);
      set({ pendingApprovals: response.approvals });
    } catch (error) {
      console.error('Failed to fetch approvals:', error);
    }
  },

  respondToApproval: async (commandHash: string, approved: boolean) => {
    const { currentRun } = get();
    if (!currentRun) return;

    try {
      await approvalsApi.respond(currentRun.id, commandHash, approved);
      set((state) => ({
        pendingApprovals: state.pendingApprovals.filter(
          (a) => a.command_hash !== commandHash
        ),
      }));
    } catch (error) {
      set({ error: 'Failed to respond to approval' });
    }
  },

  // WebSocket events
  handleWSEvent: (event: WSEvent) => {
    switch (event.type) {
      case 'phase_change':
        set({ phase: event.phase as string, currentStepIndex: (event.step as number) || get().currentStepIndex });
        break;

      case 'message':
        set((state) => ({
          messages: [
            ...state.messages,
            {
              role: event.role as Message['role'],
              content: event.content as string,
              name: event.name as string | undefined,
            },
          ],
        }));
        break;

      case 'plan_update':
        set({ plan: event.plan as PlanStep[] });
        break;

      case 'token_update':
        // Update token count for current run
        set((state) => {
          if (!state.currentRun) return state;
          const totalTokens = event.total_tokens as number;
          return {
            currentRun: { ...state.currentRun, total_tokens: totalTokens },
            runs: state.runs.map((r) =>
              r.id === state.currentRun?.id ? { ...r, total_tokens: totalTokens } : r
            ),
          };
        });
        break;

      case 'step_start':
        set({ currentStepIndex: event.step_index as number });
        break;

      case 'step_complete':
        set((state) => ({
          plan: state.plan.map((step, idx) =>
            idx === (event.step_index as number)
              ? { ...step, status: event.status as PlanStep['status'], result: event.result as string }
              : step
          ),
        }));
        break;

      case 'search_parallel':
        set({ searchThemes: event.themes as string[] });
        break;

      case 'approval_needed':
        set((state) => ({
          pendingApprovals: [
            ...state.pendingApprovals,
            {
              command_hash: event.command_hash as string,
              run_id: get().currentRun?.id || '',
              command_text: event.command as string,
              approved: 0,
            },
          ],
        }));
        break;

      case 'run_complete':
        set({ isRunning: false, phase: 'done' });
        if (event.report) {
          set((state) => ({
            messages: [
              ...state.messages,
              { role: 'assistant', content: event.report as string, name: 'Reporter' },
            ],
          }));
        }
        break;

      case 'run_error':
        set({ isRunning: false, error: event.error as string });
        break;

      case 'run_paused':
        set({ isRunning: false, phase: 'paused' });
        break;

      case 'plan_confirmation_needed':
        set({
          plan: event.plan as PlanStep[],
          showPlanConfirmationModal: true,
          isRunning: false,
        });
        break;
    }
  },

  // UI helpers
  addMessage: (message: Message) => {
    set((state) => ({ messages: [...state.messages, message] }));
  },

  updatePlan: (plan: PlanStep[]) => {
    set({ plan });
  },

  setPhase: (phase: string) => {
    set({ phase });
  },

  clearError: () => set({ error: null }),

  reset: () => {
    set({
      currentRun: null,
      phase: 'idle',
      plan: [],
      currentStepIndex: 0,
      messages: [],
      isRunning: false,
      searchThemes: [],
      pendingApprovals: [],
      error: null,
      showPlanConfirmationModal: false,
    });
  },

  // Plan Confirmation
  confirmPlan: async (feedback?: string) => {
    const { currentRun } = get();
    if (!currentRun) return;

    set({ showPlanConfirmationModal: false, isRunning: true });

    try {
      // Send confirmation message to resume research
      const message = feedback
        ? `approve: ${feedback}`
        : 'approve';
      await researchApi.sendMessage(currentRun.id, message);
    } catch (error) {
      set({ error: 'Failed to confirm plan', isRunning: false });
    }
  },

  rejectPlan: async (feedback: string) => {
    const { currentRun } = get();
    if (!currentRun) return;

    set({ showPlanConfirmationModal: false, isRunning: true });

    try {
      // Send rejection message with feedback to regenerate plan
      await researchApi.sendMessage(currentRun.id, `reject: ${feedback}`);
    } catch (error) {
      set({ error: 'Failed to reject plan', isRunning: false });
    }
  },

  closePlanConfirmationModal: () => {
    set({ showPlanConfirmationModal: false });
  },
}));
