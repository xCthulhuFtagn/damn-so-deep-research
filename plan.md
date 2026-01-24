# Implementation Plan: Fix Research Chat Flow and Plan Confirmation UI

## Summary of Issues

### Issue 1: Research Interaction Logic
**Current:** User enters topic → creates run with that title → shows "Start Research" button → must click Start to begin
**Required:** Create chat with default name "New Chat (N)" → type query → research starts automatically → chat name updates to query

### Issue 2: Plan Confirmation Not Indicated in UI
**Current:** Process stops after plan creation (intentional) but UI doesn't indicate plan needs confirmation
**Required:** UI should show a clear indication that the plan is awaiting confirmation before proceeding

### Issue 3: Missing Dependency
`langchain-text-splitters` is used but not declared in pyproject.toml

---

## Implementation Plan

### Part 1: Fix Research Interaction Logic

#### 1.1 Update ResearchPage.tsx
**File:** `frontend/src/components/ResearchPage.tsx`

- Remove the title input form entirely
- Change "+ New Research" button to directly create a run with default name "New Chat"
- Add duplicate counter logic: "New Chat", "New Chat (2)", "New Chat (3)", etc.

```tsx
// Replace handleCreateRun with:
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

  const run = await createRun(getNextName());
  navigate(`/run/${run.id}`);
};
```

#### 1.2 Update ChatContainer.tsx
**File:** `frontend/src/components/Chat/ChatContainer.tsx`

- Remove "Start Research" button entirely
- Keep only "Pause" button (when running)
- Change empty state message to prompt for query input
- When first message is sent, research starts automatically (already works via `/message` endpoint)

#### 1.3 Update researchStore.ts
**File:** `frontend/src/stores/researchStore.ts`

- Add `updateRunTitle` action to update run title via API
- Modify `sendMessage` to:
  1. Check if this is the first message (no existing state/messages)
  2. If first message, also update the run title to the query text

#### 1.4 Add API method for updating run title
**File:** `frontend/src/api/client.ts`

- Ensure `runsApi.update()` can update the title

#### 1.5 Update backend to handle title updates
**File:** `backend/api/routes/runs.py` (if needed)

- Ensure PATCH/PUT endpoint supports title updates

---

### Part 2: Plan Confirmation UI (Modal Dialog)

#### 2.1 Add new phase: "awaiting_confirmation"
**File:** `backend/agents/state.py`

- Add "awaiting_confirmation" to the phase Literal type

#### 2.2 Send confirmation needed event after planner
**File:** `backend/services/research_service.py`

- After the graph pauses (returns from astream after planner), detect this state
- Broadcast a new WebSocket event: `plan_confirmation_needed` with the plan data

#### 2.3 Add WebSocket event type
**File:** `backend/api/websocket.py`

- Add `PLAN_CONFIRMATION_NEEDED` event type

#### 2.4 Handle event in frontend store
**File:** `frontend/src/stores/researchStore.ts`

- Handle `plan_confirmation_needed` event
- Set new state: `showPlanConfirmationModal: boolean`
- Add action: `confirmPlan()` - sends confirmation message and closes modal

#### 2.5 Create PlanConfirmationModal component
**File:** `frontend/src/components/Chat/PlanConfirmationModal.tsx` (new file)

- Modal dialog overlay
- Display plan steps in a scrollable list
- "Confirm Plan" button (primary) - calls `confirmPlan()` action
- "Cancel" button - closes modal without confirming
- Optionally: Allow editing plan steps before confirming

#### 2.6 Integrate in ResearchPage
**File:** `frontend/src/components/ResearchPage.tsx`

- Render PlanConfirmationModal when `showPlanConfirmationModal` is true
- Modal sends confirmation message via `research.sendMessage("confirm")` or similar

---

### Part 3: Fix Missing Dependency

#### 3.1 Update pyproject.toml
**File:** `pyproject.toml`

Add to dependencies:
```toml
"langchain-text-splitters>=0.3.0",
```

---

## Files to Modify

| File | Changes |
|------|---------|
| `frontend/src/components/ResearchPage.tsx` | Remove title form, auto-generate "New Chat (N)", add PlanConfirmationModal |
| `frontend/src/components/Chat/ChatContainer.tsx` | Remove Start button, update empty state message |
| `frontend/src/stores/researchStore.ts` | Add title update, plan confirmation state, confirmPlan action |
| `frontend/src/api/client.ts` | Ensure runsApi.update() supports title |
| `frontend/src/types/index.ts` | Add plan_confirmation_needed event type |
| `backend/agents/state.py` | Add "awaiting_confirmation" phase |
| `backend/services/research_service.py` | Broadcast plan_confirmation_needed after planner |
| `backend/api/websocket.py` | Add PLAN_CONFIRMATION_NEEDED event type |
| `pyproject.toml` | Add langchain-text-splitters dependency |

## New Files

| File | Purpose |
|------|---------|
| `frontend/src/components/Chat/PlanConfirmationModal.tsx` | Modal dialog for plan confirmation |

---

## Verification Plan

1. **Test new chat flow:**
   - Click "+ New Research" → Should immediately create "New Chat" run
   - Type a query → Research should start automatically
   - Check run title updated to the query text
   - Create another chat → Should be "New Chat (2)"

2. **Test plan confirmation modal:**
   - Start research → After planner completes, modal dialog should appear
   - Modal shows plan steps with "Confirm Plan" button
   - Click "Confirm Plan" → Modal closes, research continues automatically
   - Click outside modal or "Cancel" → Modal closes, research stays paused

3. **Test dependency:**
   - Run `pip install -e .` and verify langchain-text-splitters is installed
   - Run the application and verify no import errors
