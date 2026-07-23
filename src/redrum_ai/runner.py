import json
import time
import sys
import os
from typing import Any
from redrum_ai.config import AppConfig
from redrum_memory.database import (
    db_session,
    save_task,
    get_active_tasks,
    save_conversation_turn,
)
from redrum_ai.model import send_to_ollama
from redrum_ai.prompt import construct_prompt
from redrum_ai.tools import registry, invoke_tool, COMMAND_ALLOWLIST

MAX_RETRIES = 3
MAX_LOOP_ITERATIONS = 10

def update_task_status(db_path: str, task_id: int, status: str) -> None:
    with db_session(db_path) as conn:
        conn.execute(
            "UPDATE tasks SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, task_id)
        )

def update_task_description(db_path: str, task_id: int, description: str) -> None:
    with db_session(db_path) as conn:
        conn.execute(
            "UPDATE tasks SET description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (description, task_id)
        )

def update_task_acceptance_criteria(db_path: str, task_id: int, criteria: str) -> None:
    with db_session(db_path) as conn:
        conn.execute(
            "UPDATE tasks SET acceptance_criteria = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (criteria, task_id)
        )

def update_task_session_notes(db_path: str, task_id: int, notes: str) -> None:
    with db_session(db_path) as conn:
        conn.execute(
            "UPDATE tasks SET session_notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (notes, task_id)
        )

def summarize_git_changes(config: AppConfig, diff_text: str) -> str:
    if not diff_text.strip():
        return "No changes detected in Git."
        
    prompt = (
        "You are redrum-ai. Summarize the following Git diff clearly and concisely, "
        "grouping by files changed and highlighting key additions/deletions:\n\n"
        f"{diff_text[:4000]}\n\n"
        "Summary of Changes:"
    )
    try:
        return send_to_ollama(config, prompt)
    except Exception as exc:
        return f"Failed to summarize Git changes: {exc}"

def perform_self_review(config: AppConfig, task_title: str, acceptance_criteria: str, tool_name: str, output: str) -> dict:
    prompt = (
        "You are redrum-ai. Act as a Quality Auditor. Review the output of the executed tool to verify "
        "if the task step is successfully completed and matches the acceptance criteria.\n\n"
        f"Task Step: {task_title}\n"
        f"Acceptance Criteria: {acceptance_criteria or 'None'}\n"
        f"Tool Invoked: {tool_name}\n"
        f"Tool Output:\n{output[:1500]}\n\n"
        "Determine if the outcome meets the criteria. Respond ONLY with a valid JSON object in this format:\n"
        "{\n"
        "  \"success\": true,\n"
        "  \"findings\": \"Summarize findings, outcomes, or remaining tasks.\"\n"
        "}"
    )
    try:
        resp = send_to_ollama(config, prompt).strip()
        if resp.startswith("```"):
            lines = resp.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            resp = "\n".join(lines).strip()
        return json.loads(resp)
    except Exception as exc:
        return {"success": True, "findings": f"Self-review parser failed or skipped: {exc}"}

def run_agent_loop(config: AppConfig, query: str) -> str:
    # 1. Check if there are existing active tasks
    active_tasks = get_active_tasks(config.db_path, config.project_slug)
    resume = False
    
    if active_tasks:
        if sys.stdin.isatty():
            print(f"\n⚠️  [ACTIVE PLAN DETECTED]: Found {len(active_tasks)} active tasks in workspace.")
            ans = input("Would you like to resume the existing plan? (Y/n): ").strip().lower()
            if ans != "n":
                resume = True
        else:
            resume = True

    if not resume:
        # Clear existing non-done tasks for this project to start fresh
        with db_session(config.db_path) as conn:
            conn.execute("DELETE FROM tasks WHERE project_slug = ? AND status != 'done'", (config.project_slug,))
        
        # Act as Planner
        if config.verbose:
            print("Planner: Generating step-by-step execution plan with acceptance criteria...", file=sys.stderr)
            
        planning_prompt = construct_prompt(config, query, mode="planning", response_format="plan")
        planning_prompt += (
            "\n\nOutput a valid JSON list containing the plan steps. "
            "Each step must be a JSON object with:\n"
            "- 'title': step name\n"
            "- 'description': task detail\n"
            "- 'priority': 'low', 'medium', 'high', 'critical'\n"
            "- 'acceptance_criteria': explicit criteria to mark this step completed\n\n"
            "Do NOT include any extra conversational text or markdown code block markers outside of the JSON. "
            "Example format:\n"
            "[\n"
            "  {\n"
            "    \"title\": \"Step 1\",\n"
            "    \"description\": \"Do something\",\n"
            "    \"priority\": \"medium\",\n"
            "    \"acceptance_criteria\": \"Output files exist and contain content\"\n"
            "  }\n"
            "]"
        )
        
        raw_plan = send_to_ollama(config, planning_prompt)
        
        clean_plan = raw_plan.strip()
        if clean_plan.startswith("```"):
            lines = clean_plan.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_plan = "\n".join(lines).strip()
            
        try:
            steps = json.loads(clean_plan)
            if not isinstance(steps, list):
                steps = [{"title": "Execute request", "description": query, "priority": "medium", "acceptance_criteria": "Successful execution response."}]
        except Exception:
            steps = [{"title": "Execute request", "description": query, "priority": "medium", "acceptance_criteria": "Successful execution response."}]
            
        for step in steps:
            save_task(
                config.db_path,
                title=step.get("title", "Task"),
                description=step.get("description", ""),
                status="backlog",
                priority=step.get("priority", "medium"),
                project_slug=config.project_slug,
                workspace_path=config.workspace_path,
                acceptance_criteria=step.get("acceptance_criteria", ""),
                session_notes=""
            )
            
        active_tasks = get_active_tasks(config.db_path, config.project_slug)
        print(f"Planner: Created plan with {len(active_tasks)} tasks.")

    # 2. Iterate through plan tasks
    tool_results = []
    
    for task in active_tasks:
        task_id = task["id"]
        task_title = task["title"]
        
        # Interactive execution checkpoint
        if sys.stdin.isatty():
            print(f"\n📍 [CHECKPOINT]: Next task is: '{task_title}'")
            print(f"   Objective: {task.get('description', '')}")
            print(f"   Acceptance Criteria: {task.get('acceptance_criteria', 'None')}")
            ans = input("Proceed? (Y/n/edit): ").strip().lower()
            if ans == "n":
                print("Execution paused. You can resume later.")
                return "Execution paused by user at checkpoint."
            elif ans == "edit":
                new_title = input(f"New Title (leave empty to keep: '{task_title}'): ").strip()
                if new_title:
                    with db_session(config.db_path) as conn:
                        conn.execute("UPDATE tasks SET title = ? WHERE id = ?", (new_title, task_id))
                    task_title = new_title
                new_desc = input(f"New Description (leave empty to keep: '{task.get('description', '')}'): ").strip()
                if new_desc:
                    update_task_description(config.db_path, task_id, new_desc)
                    task["description"] = new_desc
                new_criteria = input(f"New Acceptance Criteria (leave empty to keep): ").strip()
                if new_criteria:
                    update_task_acceptance_criteria(config.db_path, task_id, new_criteria)
                    task["acceptance_criteria"] = new_criteria
        else:
            print(f"\n🚀 [EXECUTING TASK]: {task_title}")
            
        update_task_status(config.db_path, task_id, "in_progress")
        
        iterations = 0
        retries = 0
        task_done = False
        
        while not task_done and iterations < MAX_LOOP_ITERATIONS:
            iterations += 1
            
            # Construct execution prompt
            exec_prompt = construct_prompt(
                config,
                user_query=f"Executing Step: {task_title}. Details: {task['description']}. Acceptance Criteria: {task.get('acceptance_criteria', '')}",
                mode="execution",
                response_format="report",
                tool_results=tool_results
            )
            exec_prompt += (
                "\n\nYou MUST respond ONLY with a JSON object. Do NOT wrap it in markdown. Do NOT write any chat content. "
                "Structure your JSON response as follows:\n"
                "{\n"
                "  \"thought\": \"Brief description of your thinking process.\",\n"
                "  \"tool\": \"Name of the tool to invoke (e.g. read_file, execute_shell, git_tool, list_directory, web_search) or null if none needed.\",\n"
                "  \"arguments\": {\"param_name\": \"value\"},\n"
                "  \"status\": \"'in_progress' or 'done'\"\n"
                "}"
            )
            
            raw_response = send_to_ollama(config, exec_prompt)
            clean_resp = raw_response.strip()
            if clean_resp.startswith("```"):
                lines = clean_resp.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_resp = "\n".join(lines).strip()
                
            try:
                action = json.loads(clean_resp)
            except Exception as exc:
                print(f"Error parsing LLM response as JSON: {exc}. Raw: {raw_response}", file=sys.stderr)
                retries += 1
                if retries >= MAX_RETRIES:
                    print("Max retries exceeded parsing response. Escalating to human.", file=sys.stderr)
                    update_task_status(config.db_path, task_id, "blocked")
                    return "Task execution blocked due to repeated parser failures."
                # Exponential backoff
                time.sleep(2 ** retries)
                continue
                
            thought = action.get("thought", "")
            tool_name = action.get("tool")
            args = action.get("arguments", {})
            status = action.get("status", "in_progress")
            
            if thought:
                print(f"🤖 [THOUGHT]: {thought}")
                
            if tool_name:
                print(f"🛠️  [TOOL CALL]: {tool_name} with args: {args}")
                try:
                    result = invoke_tool(
                        tool_name=tool_name,
                        args=args,
                        workspace_path=config.workspace_path,
                        db_path=config.db_path,
                        dry_run=False
                    )
                    
                    if isinstance(result, dict):
                        out_str = result.get("output", "")
                        exit_code = result.get("exit_code", 0)
                    else:
                        out_str = str(result)
                        exit_code = 0 if not out_str.startswith("Error") else 1
                        
                    # Git changes auto summarization
                    if tool_name == "git_tool" and "diff" in args.get("action", ""):
                        summary_diff = summarize_git_changes(config, out_str)
                        print(f"📝 [GIT DIFF SUMMARY]:\n{summary_diff}")
                        
                    # Self review pass after action
                    review_res = perform_self_review(
                        config=config,
                        task_title=task_title,
                        acceptance_criteria=task.get("acceptance_criteria", ""),
                        tool_name=tool_name,
                        output=out_str
                    )
                    
                    findings = review_res.get("findings", "")
                    review_ok = review_res.get("success", True)
                    print(f"🔎 [SELF-REVIEW]: success={review_ok}, findings={findings}")
                    
                    # Store session notes/findings
                    update_task_session_notes(config.db_path, task_id, findings)
                    
                    status_lbl = "success" if (exit_code == 0 and review_ok) else "failed"
                    
                    tool_results.append({
                        "tool": tool_name,
                        "arguments": args,
                        "output": out_str,
                        "status": status_lbl
                    })
                    
                    if exit_code != 0 or not review_ok:
                        retries += 1
                        if retries >= MAX_RETRIES:
                            print(f"Tool execution or review check failed repeatedly. Escalating.", file=sys.stderr)
                            update_task_status(config.db_path, task_id, "blocked")
                            return f"Task step '{task_title}' blocked on tool failure/review: {out_str}"
                        # Exponential backoff
                        backoff = 2 ** retries
                        print(f"Action check failed, retrying (attempt {retries}/{MAX_RETRIES}) in {backoff}s...", file=sys.stderr)
                        time.sleep(backoff)
                    else:
                        retries = 0
                        
                except Exception as exc:
                    print(f"Exception during tool execution: {exc}", file=sys.stderr)
                    tool_results.append({
                        "tool": tool_name,
                        "arguments": args,
                        "output": f"Exception: {exc}",
                        "status": "failed"
                    })
                    
            if status == "done":
                task_done = True
                update_task_status(config.db_path, task_id, "done")
                print(f"✅ [TASK COMPLETED]: {task_title}")
                
        if not task_done:
            print(f"⚠️  [WARNING]: Loop limit reached for task: {task_title}", file=sys.stderr)
            update_task_status(config.db_path, task_id, "needs_review")
            
    # 3. Final review mode
    if config.verbose:
        print("Reviewer: Auditing completed work...", file=sys.stderr)
        
    review_prompt = construct_prompt(
        config,
        user_query=query,
        mode="review",
        response_format="report",
        tool_results=tool_results
    )
    review_prompt += "\n\nProvide your final summary report of completed tasks, changes made, and next steps."
    
    final_report = send_to_ollama(config, review_prompt)
    return final_report
