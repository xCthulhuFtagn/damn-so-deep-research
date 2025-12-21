#!/usr/bin/env python3
"""
Test script to validate agent configuration without running full Streamlit app.
This checks:
1. All agents are properly configured
2. Tool names don't have artifacts
3. Handoffs are correctly set up
4. Model settings are applied
"""

import sys
from research_agents import (
    planner_agent,
    executor_agent,
    evaluator_agent,
    strategist_agent,
    reporter_agent,
    transfer_to_executor,
    transfer_to_evaluator,
    transfer_to_strategist,
    transfer_to_reporter,
    transfer_to_planner,
)
import tools


def test_agent_configuration():
    """Test that all agents are properly configured."""
    
    print("=" * 70)
    print("AGENT CONFIGURATION TEST")
    print("=" * 70)
    
    agents = [
        ("Planner", planner_agent),
        ("Executor", executor_agent),
        ("Evaluator", evaluator_agent),
        ("Strategist", strategist_agent),
        ("Reporter", reporter_agent),
    ]
    
    all_passed = True
    
    for name, agent in agents:
        print(f"\n{'─' * 70}")
        print(f"Testing: {name}")
        print(f"{'─' * 70}")
        
        # Check basic attributes
        assert agent.name == name, f"❌ Agent name mismatch: {agent.name}"
        print(f"✅ Agent name: {agent.name}")
        
        # Check tools
        tool_count = len(agent.tools) if agent.tools else 0
        print(f"✅ Tools count: {tool_count}")
        
        if agent.tools:
            print(f"   Tool names:")
            for tool in agent.tools:
                tool_name = getattr(tool, 'name', getattr(tool, '__name__', 'unknown'))
                
                # Check for artifacts in tool name
                if '<|' in str(tool_name):
                    print(f"   ❌ ARTIFACT DETECTED: {tool_name}")
                    all_passed = False
                else:
                    print(f"   ✅ {tool_name}")
        
        # Check handoffs
        if agent.handoffs:
            print(f"✅ Handoffs count: {len(agent.handoffs)}")
            print(f"   Handoff targets:")
            for handoff in agent.handoffs:
                handoff_name = getattr(handoff, 'name', getattr(handoff, '__name__', 'unknown'))
                
                # Check for artifacts
                if '<|' in str(handoff_name):
                    print(f"   ❌ ARTIFACT DETECTED: {handoff_name}")
                    all_passed = False
                else:
                    print(f"   ✅ {handoff_name}")
        else:
            print(f"ℹ️  No handoffs configured")
        
        # Check model settings
        if agent.model_settings:
            settings = agent.model_settings
            print(f"✅ Model Settings:")
            print(f"   parallel_tool_calls: {getattr(settings, 'parallel_tool_calls', 'not set')}")
            print(f"   tool_choice: {getattr(settings, 'tool_choice', 'not set')}")
            print(f"   temperature: {getattr(settings, 'temperature', 'not set')}")
            
            # Validate critical settings
            if hasattr(settings, 'parallel_tool_calls') and settings.parallel_tool_calls is not False:
                print(f"   ⚠️  WARNING: parallel_tool_calls should be False")
                all_passed = False
        else:
            print(f"ℹ️  No model settings configured")
        
        # Check instructions
        if agent.instructions:
            instr = agent.instructions
            print(f"✅ Instructions length: {len(instr)} chars")
            
            # Check for key phrases
            key_phrases = [
                ("EXACT tool names", "exact name enforcement"),
                ("EXACTLY ONE tool", "single tool per turn"),
                ("FORBIDDEN", "explicit prohibitions"),
            ]
            
            for phrase, description in key_phrases:
                if phrase in instr:
                    print(f"   ✅ Contains: {description}")
                else:
                    print(f"   ⚠️  Missing: {description}")
        else:
            print(f"❌ No instructions configured!")
            all_passed = False
    
    print(f"\n{'=' * 70}")
    
    return all_passed


def test_handoff_functions():
    """Test that handoff functions are properly defined."""
    
    print("\n" + "=" * 70)
    print("HANDOFF FUNCTIONS TEST")
    print("=" * 70)
    
    handoffs = [
        ("transfer_to_executor", transfer_to_executor),
        ("transfer_to_evaluator", transfer_to_evaluator),
        ("transfer_to_strategist", transfer_to_strategist),
        ("transfer_to_reporter", transfer_to_reporter),
        ("transfer_to_planner", transfer_to_planner),
    ]
    
    all_passed = True
    
    for name, func in handoffs:
        print(f"\n{'─' * 70}")
        print(f"Testing: {name}")
        
        # Check function name
        func_name = getattr(func, 'name', getattr(func, '__name__', 'unknown'))
        
        if '<|' in str(func_name):
            print(f"❌ ARTIFACT DETECTED in function name: {func_name}")
            all_passed = False
        else:
            print(f"✅ Function name clean: {func_name}")
        
        # Check docstring
        if func.__doc__:
            print(f"✅ Has docstring: {len(func.__doc__)} chars")
        else:
            print(f"⚠️  No docstring")
    
    print(f"\n{'=' * 70}")
    
    return all_passed


def test_tool_functions():
    """Test that tool functions don't have artifacts."""
    
    print("\n" + "=" * 70)
    print("TOOL FUNCTIONS TEST")
    print("=" * 70)
    
    tool_funcs = [
        ("add_steps_to_plan", tools.add_steps_to_plan),
        ("get_current_plan_step", tools.get_current_plan_step),
        ("get_completed_research_context", tools.get_completed_research_context),
        ("submit_step_result", tools.submit_step_result),
        ("mark_step_failed", tools.mark_step_failed),
        ("web_search", tools.web_search),
        ("read_file", tools.read_file),
        ("execute_terminal_command", tools.execute_terminal_command),
    ]
    
    all_passed = True
    
    for name, func in tool_funcs:
        print(f"\n{'─' * 70}")
        print(f"Testing: {name}")
        
        # Check function name
        func_name = getattr(func, 'name', getattr(func, '__name__', 'unknown'))
        
        if '<|' in str(func_name):
            print(f"❌ ARTIFACT DETECTED: {func_name}")
            all_passed = False
        else:
            print(f"✅ Function name clean: {func_name}")
        
        # Check expected name matches
        if func_name == name or func_name == 'unknown':
            print(f"✅ Name matches expected")
        else:
            print(f"⚠️  Name mismatch: expected '{name}', got '{func_name}'")
    
    print(f"\n{'=' * 70}")
    
    return all_passed


def main():
    """Run all tests."""
    
    print("\n" + "🔧 " * 35)
    print("DEEP RESEARCH AGENT CONFIGURATION TEST SUITE")
    print("🔧 " * 35 + "\n")
    
    results = []
    
    try:
        results.append(("Agent Configuration", test_agent_configuration()))
    except Exception as e:
        print(f"❌ Agent Configuration Test Failed: {e}")
        results.append(("Agent Configuration", False))
    
    try:
        results.append(("Handoff Functions", test_handoff_functions()))
    except Exception as e:
        print(f"❌ Handoff Functions Test Failed: {e}")
        results.append(("Handoff Functions", False))
    
    try:
        results.append(("Tool Functions", test_tool_functions()))
    except Exception as e:
        print(f"❌ Tool Functions Test Failed: {e}")
        results.append(("Tool Functions", False))
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status} - {test_name}")
    
    all_passed = all(passed for _, passed in results)
    
    print("=" * 70)
    
    if all_passed:
        print("\n🎉 ALL TESTS PASSED! Configuration looks good.")
        print("\nYou can now run: LOG_LEVEL=DEBUG streamlit run main.py")
        return 0
    else:
        print("\n⚠️  SOME TESTS FAILED. Review the output above.")
        print("\nCommon fixes:")
        print("1. Restart Python to reload modules")
        print("2. Check for syntax errors in research_agents.py")
        print("3. Verify no manual edits introduced artifacts")
        return 1


if __name__ == "__main__":
    sys.exit(main())

