"""
Research service for graph execution orchestration.

Manages the lifecycle of research runs including start, pause, resume.
"""

import asyncio
import logging
from typing import Any, Dict, Optional, Set

from backend.agents.graph import create_research_graph
from backend.agents.state import ResearchState, create_initial_state
from backend.core.checkpointer import get_checkpointer, get_thread_config
from backend.core.llm import get_llm_provider
from backend.persistence.database import get_db_service
from backend.services.notification_service import get_notification_service

logger = logging.getLogger(__name__)


class ResearchService:
    """
    Service for managing research graph execution.

    Handles starting, pausing, resuming, and monitoring research runs.
    """

    def __init__(self):
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._pause_flags: Set[str] = set()
        self._approval_events: Dict[str, asyncio.Event] = {}
        self._approval_results: Dict[str, bool] = {}
        self._graph = None
        # Track tokens per run for aggregation
        self._run_tokens: Dict[str, int] = {}

    async def _get_graph(self):
        """Get or create the compiled research graph."""
        if self._graph is None:
            checkpointer = await get_checkpointer()
            self._graph = create_research_graph(checkpointer=checkpointer)
        return self._graph

    async def _on_tokens(self, run_id: str, input_tokens: int, output_tokens: int) -> None:
        """
        Callback for token usage tracking.

        Updates database and sends WebSocket notification.
        """
        total_new = input_tokens + output_tokens
        if total_new == 0:
            return

        try:
            db = await get_db_service()
            notification = get_notification_service()

            # Update database
            await db.increment_tokens(run_id, total_new)

            # Track cumulative tokens for this run
            self._run_tokens[run_id] = self._run_tokens.get(run_id, 0) + total_new

            # Send WebSocket notification
            await notification.notify_token_update(
                run_id,
                input_tokens,
                output_tokens,
                self._run_tokens[run_id],
            )

            logger.debug(f"Token update for run {run_id}: +{total_new} (total: {self._run_tokens[run_id]})")
        except Exception as e:
            logger.warning(f"Failed to track tokens for run {run_id}: {e}")

    def is_running(self, run_id: str) -> bool:
        """Check if a run is currently executing."""
        task = self._running_tasks.get(run_id)
        return task is not None and not task.done()

    async def execute_research(
        self,
        run_id: str,
        user_id: str,
        initial_query: str,
    ) -> None:
        """
        Execute research for a run.

        This is the main entry point for starting research execution.
        """
        logger.info(f"Starting research execution for run {run_id}")

        notification = get_notification_service()
        db = await get_db_service()

        # Setup token tracking
        llm_provider = get_llm_provider()
        llm_provider.set_token_callback(run_id, self._on_tokens)
        self._run_tokens[run_id] = 0

        try:
            # Create initial state
            state = create_initial_state(
                run_id=run_id,
                user_id=user_id,
                query=initial_query,
            )

            # Get graph and config
            graph = await self._get_graph()
            config = get_thread_config(run_id, user_id)

            # Update run status
            await db.update_run(run_id, status="active")

            # Execute graph
            logger.info(f"Invoking graph for run {run_id}")

            async for namespace, event in graph.astream(state, config, stream_mode="updates", subgraphs=True):
                # Check pause flag
                if run_id in self._pause_flags:
                    logger.info(f"Pause requested for run {run_id}")
                    await notification.notify_run_paused(run_id)
                    self._pause_flags.discard(run_id)
                    return

                # Process event and send notifications
                await self._process_graph_event(run_id, event)

            # Get final state to check if graph is interrupted or completed
            final_state = await graph.aget_state(config)

            # Check if graph is waiting for input (interrupted)
            if final_state and final_state.next:
                # Graph is interrupted, waiting for user input
                logger.info(f"Graph interrupted for run {run_id}, waiting for user input")
                phase = final_state.values.get("phase", "")

                # If awaiting confirmation, send the plan confirmation event
                if phase == "awaiting_confirmation":
                    plan = final_state.values.get("plan", [])
                    # Convert PlanStep TypedDicts to regular dicts for JSON serialization
                    plan_dicts = [dict(step) for step in plan]
                    await notification.notify_plan_confirmation_needed(run_id, plan_dicts)
                    await db.update_run(run_id, status="awaiting_confirmation")

                # If awaiting terminal approval (future feature)
                elif phase == "awaiting_terminal":
                    pending = final_state.values.get("pending_terminal", {})
                    if pending:
                        logger.info(f"Terminal approval needed for run {run_id}")
                        await db.update_run(run_id, status="awaiting_terminal")
                        # Note: Terminal approval UI/API endpoint would be needed
                return

            # Update run status
            await db.update_run(run_id, status="completed")

            # Notify completion
            await notification.notify_run_complete(run_id)

            logger.info(f"Research completed for run {run_id}")

        except Exception as e:
            logger.exception(f"Research execution error for run {run_id}: {e}")
            await db.update_run(run_id, status="failed")
            await notification.notify_run_error(run_id, str(e))

        finally:
            # Clean up
            self._running_tasks.pop(run_id, None)
            llm_provider.clear_token_callback()

    async def _process_graph_event(
        self,
        run_id: str,
        event: Dict[str, Any],
    ) -> None:
        """Process a graph stream event and send notifications."""
        notification = get_notification_service()

        for node_name, node_output in event.items():
            if not isinstance(node_output, dict):
                continue

            # Notify plan updates
            if "plan" in node_output:
                plan = node_output["plan"]
                # Convert TypedDicts to regular dicts if needed
                plan_dicts = [dict(step) if hasattr(step, "_asdict") else dict(step) for step in plan]
                await notification.notify_plan_update(run_id, plan_dicts)

            # Notify phase changes

            if "phase" in node_output:
                phase = node_output["phase"]
                await notification.notify_phase_change(
                    run_id,
                    phase,
                    node_output.get("current_step_index"),
                )

                # If phase is awaiting_confirmation, send plan confirmation needed event
                if phase == "awaiting_confirmation" and "plan" in node_output:
                    await notification.notify_plan_confirmation_needed(
                        run_id,
                        node_output["plan"],
                    )

            # Notify step starts
            if node_name in ["identify_themes", "theme_identifier"]:
                plan = node_output.get("plan", [])
                idx = node_output.get("current_step_index", 0)
                if idx < len(plan):
                    await notification.notify_step_start(
                        run_id,
                        idx,
                        plan[idx].get("description", ""),
                    )

            # Notify parallel searches
            # Only notify if we have themes AND we are in the searching phase (search_dispatcher)
            # OR if it's the theme_identifier (initial identification)
            if "search_themes" in node_output and node_output["search_themes"]:
                should_notify = False
                if node_name == "theme_identifier":
                    should_notify = True
                elif node_name == "search_dispatcher":
                    should_notify = True
                elif node_output.get("phase") == "searching":
                    should_notify = True
                
                if should_notify:
                    await notification.notify_search_parallel(
                        run_id,
                        node_output["search_themes"],
                    )

            # Handle executor subgraph events
            if "executor_decision" in node_output:
                decision = node_output["executor_decision"]
                if decision:
                    tool = decision.get("decision", "")
                    if tool and tool != "DONE":
                        logger.debug(f"Executor using tool: {tool}")

            # Handle pending terminal commands (for future approval flow)
            if "pending_terminal" in node_output and node_output["pending_terminal"]:
                pending = node_output["pending_terminal"]
                logger.info(f"Terminal command pending: {pending.get('command', '')[:50]}...")

            # Notify messages
            if "messages" in node_output:
                for msg in node_output["messages"]:
                    if hasattr(msg, "content"):
                        await notification.notify_message(
                            run_id,
                            getattr(msg, "type", "unknown"),
                            msg.content,
                            getattr(msg, "name", None),
                        )

    async def pause_research(self, run_id: str) -> None:
        """Request pause for a running research."""
        self._pause_flags.add(run_id)
        logger.info(f"Pause flag set for run {run_id}")

    async def resume_with_input(
        self,
        run_id: str,
        user_input: str,
    ) -> None:
        """Resume a paused research with user input."""
        logger.info(f"Resuming run {run_id} with input: {user_input[:50]}...")

        notification = get_notification_service()
        db = await get_db_service()

        # Setup token tracking (resume with existing count)
        llm_provider = get_llm_provider()
        llm_provider.set_token_callback(run_id, self._on_tokens)
        # Load existing token count from database
        run = await db.get_run(run_id)
        if run:
            self._run_tokens[run_id] = run.total_tokens

        try:
            graph = await self._get_graph()

            # Get current state
            run = await db.get_run(run_id)
            if not run:
                logger.error(f"Run not found: {run_id}")
                return

            config = get_thread_config(run_id, run.user_id)
            current_state = await graph.aget_state(config)

            if not current_state or not current_state.values:
                logger.error(f"No state found for run {run_id}")
                return

            # Check if this is a plan rejection - need to re-plan
            is_rejection = user_input.lower().startswith("reject:")

            if is_rejection:
                # Extract feedback from rejection
                feedback = user_input[7:].strip()  # Remove "reject:" prefix
                logger.info(f"Plan rejected for run {run_id}, feedback: {feedback}")

                # Update state with feedback and set replan flag
                # When graph resumes, identify_themes will see needs_replan=True
                # and route back to planner via the conditional edge
                await graph.aupdate_state(
                    config,
                    {
                        "user_response": feedback,
                        "needs_replan": True,
                    },
                )

                # Notify user of re-planning
                await notification.notify_phase_change(run_id, "planning")
                await notification.notify_message(
                    run_id,
                    "assistant",
                    f"Regenerating plan based on your feedback: {feedback}",
                    name="System",
                )
            else:
                # Normal approval - just update user_response
                # Strip "approve:" prefix if present
                response = user_input
                if user_input.lower().startswith("approve:"):
                    response = user_input[8:].strip()
                elif user_input.lower() == "approve":
                    response = ""

                await graph.aupdate_state(
                    config,
                    {
                        "user_response": response,
                        "phase": "identifying_themes",  # Move to next phase
                    },
                )

            # Resume execution
            await db.update_run(run_id, status="active")

            async for namespace, event in graph.astream(None, config, stream_mode="updates", subgraphs=True):
                if run_id in self._pause_flags:
                    await notification.notify_run_paused(run_id)
                    self._pause_flags.discard(run_id)
                    return

                await self._process_graph_event(run_id, event)

            # Check if graph is interrupted again
            final_state = await graph.aget_state(config)
            if final_state and final_state.next:
                logger.info(f"Graph interrupted again for run {run_id}")
                phase = final_state.values.get("phase", "")
                if phase == "awaiting_confirmation":
                    plan = final_state.values.get("plan", [])
                    plan_dicts = [dict(step) for step in plan]
                    await notification.notify_plan_confirmation_needed(run_id, plan_dicts)
                    await db.update_run(run_id, status="awaiting_confirmation")
                elif phase == "awaiting_terminal":
                    pending = final_state.values.get("pending_terminal", {})
                    if pending:
                        logger.info(f"Terminal approval needed for run {run_id}")
                        await db.update_run(run_id, status="awaiting_terminal")
                return

            await db.update_run(run_id, status="completed")
            await notification.notify_run_complete(run_id)
            logger.info(f"Research completed for run {run_id}")

        except Exception as e:
            logger.exception(f"Resume error for run {run_id}: {e}")
            await db.update_run(run_id, status="failed")
            await notification.notify_run_error(run_id, str(e))

        finally:
            llm_provider.clear_token_callback()

    async def get_state(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get current state for a run."""
        try:
            graph = await self._get_graph()
            db = await get_db_service()

            run = await db.get_run(run_id)
            if not run:
                return None

            config = get_thread_config(run_id, run.user_id)
            state = await graph.aget_state(config)

            if state and state.values:
                return dict(state.values)
            return None

        except Exception as e:
            logger.error(f"Error getting state for run {run_id}: {e}")
            return None

    async def handle_approval_response(
        self,
        run_id: str,
        command_hash: str,
        approved: bool,
    ) -> None:
        """Handle an approval response from the user."""
        key = f"{run_id}:{command_hash}"
        self._approval_results[key] = approved

        # Signal waiting task if any
        event = self._approval_events.get(key)
        if event:
            event.set()

        logger.info(f"Approval response handled: {command_hash} = {approved}")

    async def resume_with_terminal_approval(
        self,
        run_id: str,
        approved: bool,
    ) -> None:
        """
        Resume a run that's waiting for terminal command approval.

        Args:
            run_id: The research run ID
            approved: Whether the terminal command was approved
        """
        logger.info(f"Terminal approval for run {run_id}: {approved}")

        notification = get_notification_service()
        db = await get_db_service()

        try:
            graph = await self._get_graph()

            run = await db.get_run(run_id)
            if not run:
                logger.error(f"Run not found: {run_id}")
                return

            config = get_thread_config(run_id, run.user_id)
            current_state = await graph.aget_state(config)

            if not current_state or not current_state.values:
                logger.error(f"No state found for run {run_id}")
                return

            pending = current_state.values.get("pending_terminal", {})
            if not pending:
                logger.warning(f"No pending terminal for run {run_id}")
                return

            if not approved:
                # Terminal was denied - record as failed and continue
                from backend.agents.state import ExecutorToolCall

                tool_history = current_state.values.get("executor_tool_history", [])
                failed_call = ExecutorToolCall(
                    id=len(tool_history) + 1,
                    tool="terminal",
                    params={"command": pending.get("command", "")},
                    result=None,
                    success=False,
                    error="Command execution denied by user",
                )

                await graph.aupdate_state(
                    config,
                    {
                        "executor_tool_history": failed_call,
                        "executor_call_count": 1,
                        "pending_terminal": None,
                        "phase": "executing",
                    },
                )

                await notification.notify_message(
                    run_id,
                    "system",
                    f"Terminal command denied: {pending.get('command', '')[:50]}...",
                    name="System",
                )
            else:
                # Terminal was approved - clear pending and continue
                # The terminal_exec node will handle execution
                await graph.aupdate_state(
                    config,
                    {
                        "phase": "executing",
                    },
                )

            # Resume execution
            await db.update_run(run_id, status="active")

            # Setup token tracking
            llm_provider = get_llm_provider()
            llm_provider.set_token_callback(run_id, self._on_tokens)
            self._run_tokens[run_id] = run.total_tokens

            async for namespace, event in graph.astream(None, config, stream_mode="updates", subgraphs=True):
                if run_id in self._pause_flags:
                    await notification.notify_run_paused(run_id)
                    self._pause_flags.discard(run_id)
                    return

                await self._process_graph_event(run_id, event)

            # Check final state
            final_state = await graph.aget_state(config)
            if final_state and final_state.next:
                phase = final_state.values.get("phase", "")
                if phase == "awaiting_confirmation":
                    plan = final_state.values.get("plan", [])
                    plan_dicts = [dict(step) for step in plan]
                    await notification.notify_plan_confirmation_needed(run_id, plan_dicts)
                    await db.update_run(run_id, status="awaiting_confirmation")
                elif phase == "awaiting_terminal":
                    await db.update_run(run_id, status="awaiting_terminal")
                return

            await db.update_run(run_id, status="completed")
            await notification.notify_run_complete(run_id)
            logger.info(f"Research completed for run {run_id}")

        except Exception as e:
            logger.exception(f"Terminal approval error for run {run_id}: {e}")
            await db.update_run(run_id, status="failed")
            await notification.notify_run_error(run_id, str(e))

        finally:
            llm_provider = get_llm_provider()
            llm_provider.clear_token_callback()


# Global instance
_research_service: Optional[ResearchService] = None


async def get_research_service() -> ResearchService:
    """Get the global ResearchService instance."""
    global _research_service
    if _research_service is None:
        _research_service = ResearchService()
    return _research_service
