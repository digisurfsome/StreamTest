"""
StreamTest Dashboard
====================
A unified interface for building, editing, and testing Streamlit apps.

Modes:
1. BUILD - Create new app from scratch based on prompt
2. EDIT - Add features to existing app based on blueprint
3. TEST - Test pre-built app only

All modes feed into the auto-test-fix loop.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# Configuration
PROJECTS_DIR = Path("projects")
PROJECTS_DIR.mkdir(exist_ok=True)

CLAUDE_MODEL = "claude-opus-4-5-20250929"  # Opus 4.5 - the ONLY model for coding

# Default prompts (editable in Settings)
DEFAULT_ANALYSIS_PROMPT = """You are a senior Python developer and QA engineer. Analyze this Streamlit app code for:

1. **Syntax Errors** - Any code that won't run
2. **Logic Bugs** - Incorrect behavior, edge cases
3. **Security Issues** - SQL injection, XSS, exposed secrets
4. **Best Practices** - Missing error handling, poor UX
5. **Test Scenarios** - Based on the test steps provided

Be specific about what code to change. Include actual code snippets."""

DEFAULT_FIX_PROMPT = """Fix ONLY this specific issue in the code. Make the minimal change needed.

RULES:
1. Only fix THIS ONE issue
2. Make minimal changes
3. Don't refactor or improve other parts
4. Keep all existing functionality
5. Return the COMPLETE code with just this fix applied

Return ONLY the complete Python code, no explanations."""

DEFAULT_JUDGE_PROMPT = """You are Code Review Judge. Review the proposed code changes.

Consider:
1. Will this correctly implement the feature?
2. Does it follow the surgical edit principle (minimal changes)?
3. Are there any bugs or issues?
4. Is anything missing?

Provide your verdict: APPROVE, REJECT, or NEEDS_REVISION."""


def init_session_state():
    """Initialize session state variables."""
    defaults = {
        "mode": "TEST",
        "current_project": None,
        "logs": [],
        "loop_count": 0,
        "status": "idle",
        "planned_changes": [],
        # Editable prompts
        "analysis_prompt": DEFAULT_ANALYSIS_PROMPT,
        "fix_prompt": DEFAULT_FIX_PROMPT,
        "judge_prompt": DEFAULT_JUDGE_PROMPT,
        # Store fixed code for download
        "final_fixed_code": None,
        "final_project_name": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def get_client():
    """Get Anthropic client."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        st.error("ANTHROPIC_API_KEY not found in environment!")
        st.info("For Railway: Go to Settings → Shared Variables → ensure it's linked to 'web' service, then redeploy")
        return None
    return Anthropic(api_key=api_key)


def add_log(message: str):
    """Add a log entry."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs.append(f"[{timestamp}] {message}")


def save_project_state(project_name: str, data: dict):
    """Save project state to JSON."""
    project_dir = PROJECTS_DIR / project_name
    project_dir.mkdir(exist_ok=True)
    state_file = project_dir / "state.json"
    data["last_updated"] = datetime.now().isoformat()
    state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_project_state(project_name: str) -> dict:
    """Load project state from JSON."""
    state_file = PROJECTS_DIR / project_name / "state.json"
    if state_file.exists():
        return json.loads(state_file.read_text(encoding="utf-8"))
    return {}


def list_projects() -> list:
    """List all saved projects."""
    projects = []
    for p in PROJECTS_DIR.iterdir():
        if p.is_dir() and (p / "state.json").exists():
            projects.append(p.name)
    return sorted(projects)


# =============================================================================
# BUILD MODE - Create new app from scratch
# =============================================================================

def build_mode():
    """Build a new app from scratch."""
    st.header("🔨 Build New App")

    st.markdown("""
    Describe what you want to build. Claude will generate the code,
    then automatically test and fix it until it works.
    """)

    project_name = st.text_input("Project Name", placeholder="my_new_app")

    description = st.text_area(
        "What do you want to build?",
        height=150,
        placeholder="Describe your app in plain English...\n\nExample: A simple todo list app where users can add tasks, mark them complete, and delete them."
    )

    with st.expander("⚙️ Build Rules (Optional)"):
        build_rules = st.text_area(
            "Custom rules for the AI coder",
            height=100,
            placeholder="Example rules:\n- Use Streamlit for the UI\n- Keep the code simple and readable\n- Add comments explaining key sections"
        )

    if st.button("🚀 Build & Test", type="primary", disabled=not project_name or not description):
        if not project_name or not description:
            st.warning("Please fill in project name and description")
            return

        client = get_client()
        if not client:
            return

        st.session_state.status = "building"
        add_log(f"Starting build: {project_name}")

        # Create project directory
        project_dir = PROJECTS_DIR / project_name
        project_dir.mkdir(exist_ok=True)

        with st.spinner("Claude is building your app..."):
            default_rules = "- Use Streamlit for UI\n- Keep code clean and simple\n- Handle errors gracefully"
            rules_text = build_rules if build_rules else default_rules
            prompt = f"""You are an expert Python/Streamlit developer. Create a complete, working Streamlit app based on this description:

DESCRIPTION:
{description}

RULES:
{rules_text}

Respond with the complete Python code for a file called 'app.py'.
Only output the Python code, no explanations.
The code should be ready to run with: streamlit run app.py
"""

            try:
                response = client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=8000,
                    messages=[{"role": "user", "content": prompt}]
                )

                code = response.content[0].text

                # Clean up code if it has markdown markers
                if "```python" in code:
                    code = code.split("```python")[1].split("```")[0]
                elif "```" in code:
                    code = code.split("```")[1].split("```")[0]

                # Save the generated code
                app_file = project_dir / "app.py"
                app_file.write_text(code.strip(), encoding="utf-8")

                add_log(f"Generated app.py ({len(code)} chars)")

                # Save project state
                save_project_state(project_name, {
                    "name": project_name,
                    "description": description,
                    "rules": build_rules,
                    "mode": "build",
                    "files": ["app.py"],
                    "logs": st.session_state.logs[-20:],
                })

                st.success(f"✅ App generated! Saved to: {app_file}")
                st.code(code, language="python")

                st.session_state.current_project = project_name
                st.session_state.status = "ready_to_test"

            except Exception as e:
                st.error(f"Error: {e}")
                add_log(f"Build error: {e}")


# =============================================================================
# MULTI-AGENT CODE REVIEW SYSTEM
# =============================================================================

def create_edit_snippets(client, current_code: str, feature_description: str, edit_rules: str) -> dict:
    """First Claude instance: Create edit snippets without touching code."""
    prompt = f"""You are an expert Python developer. Analyze this code and create EDIT SNIPPETS for the requested feature.

CURRENT CODE:
```python
{current_code}
```

FEATURE TO ADD:
{feature_description}

RULES:
{edit_rules}

DO NOT provide the full updated code yet. Instead, create a detailed EDIT PLAN with specific snippets.

Respond in this exact JSON format:
{{
    "analysis": "Brief explanation of what needs to change",
    "snippets": [
        {{
            "location": "Description of where in the code (e.g., 'after imports', 'inside main function')",
            "action": "add|modify|delete",
            "original_code": "The exact code being modified (if modify/delete)",
            "new_code": "The new/replacement code",
            "reason": "Why this change is needed"
        }}
    ]
}}

Be precise and surgical. Only include changes needed for the feature."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.content[0].text

        # Extract JSON
        import re
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        st.error(f"Error creating snippets: {e}")

    return {"analysis": "Failed to create snippets", "snippets": []}


def judge_snippets(client, current_code: str, feature_description: str, snippets: dict, judge_id: int) -> dict:
    """Judge instance: Review snippets and provide verdict."""
    prompt = f"""You are Code Review Judge #{judge_id}. Review these proposed code changes.

ORIGINAL CODE:
```python
{current_code}
```

REQUESTED FEATURE:
{feature_description}

PROPOSED EDIT SNIPPETS:
{json.dumps(snippets, indent=2)}

Review each snippet and provide your judgment. Consider:
1. Will this correctly implement the feature?
2. Does it follow the surgical edit principle (minimal changes)?
3. Are there any bugs or issues?
4. Is anything missing?

Respond in this exact JSON format:
{{
    "judge_id": {judge_id},
    "overall_verdict": "APPROVE|REJECT|NEEDS_REVISION",
    "confidence": 0.0-1.0,
    "snippet_reviews": [
        {{
            "snippet_index": 0,
            "verdict": "APPROVE|REJECT|NEEDS_REVISION",
            "issue": "Description of any issue (or null if approved)",
            "suggestion": "Suggested fix (or null if approved)"
        }}
    ],
    "summary": "Overall assessment"
}}"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.content[0].text

        import re
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        st.error(f"Judge {judge_id} error: {e}")

    return {"judge_id": judge_id, "overall_verdict": "ERROR", "summary": "Failed to review"}


def apply_vetted_snippets(client, current_code: str, snippets: dict, judge_feedback: list) -> str:
    """Original Claude: Apply vetted changes considering judge feedback."""
    prompt = f"""You are the original code editor. Apply the vetted edit snippets to the code.

ORIGINAL CODE:
```python
{current_code}
```

APPROVED SNIPPETS:
{json.dumps(snippets, indent=2)}

JUDGE FEEDBACK:
{json.dumps(judge_feedback, indent=2)}

Apply all approved changes. If judges suggested improvements, incorporate them.
Return ONLY the complete updated Python code, no explanations."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.content[0].text

        # Clean up code
        if "```python" in result:
            result = result.split("```python")[1].split("```")[0]
        elif "```" in result:
            result = result.split("```")[1].split("```")[0]

        return result.strip()
    except Exception as e:
        st.error(f"Error applying changes: {e}")
        return current_code


# =============================================================================
# EDIT MODE - Add features to existing app
# =============================================================================

def edit_mode():
    """Edit/add features to existing app with multi-agent review."""
    st.header("✏️ Edit / Add Features")

    st.markdown("""
    **Multi-Agent Surgery Mode**:

    1. **Editor Claude** creates edit snippets (pre-plan)
    2. **Judge 1 & Judge 2** review the snippets independently
    3. **2-to-1 Vote** determines if changes proceed
    4. **Editor Claude** applies vetted changes
    """)

    # Project selection
    col1, col2 = st.columns(2)

    with col1:
        existing_projects = list_projects()
        selected_project = st.selectbox(
            "Select existing project",
            [""] + existing_projects,
            help="Choose a previously saved project"
        )

    with col2:
        uploaded_file = st.file_uploader(
            "Or upload Python file",
            type=["py"],
            help="Upload an existing .py file to edit"
        )

    # Load code
    current_code = ""
    project_name = ""

    if uploaded_file:
        current_code = uploaded_file.read().decode("utf-8")
        project_name = uploaded_file.name.replace(".py", "")
        st.code(current_code, language="python")
    elif selected_project:
        project_dir = PROJECTS_DIR / selected_project
        app_file = project_dir / "app.py"
        if app_file.exists():
            current_code = app_file.read_text(encoding="utf-8")
            project_name = selected_project
            with st.expander("View current code"):
                st.code(current_code, language="python")

    if not current_code:
        st.info("Select a project or upload a file to edit")
        return

    # Feature description
    feature_description = st.text_area(
        "What feature do you want to add?",
        height=150,
        placeholder="Describe the new feature...\n\nExample: Add a dark mode toggle that changes the app's color scheme"
    )

    with st.expander("⚙️ Edit Rules"):
        edit_rules = st.text_area(
            "Rules for editing (Surgery Mode)",
            value="""- ONLY add the new feature, don't change existing functionality
- Keep all existing code intact unless directly related to the new feature
- Don't refactor or "improve" unrelated code
- Preserve the existing code style and patterns
- Add minimal changes needed for the feature to work""",
            height=150
        )

    col1, col2 = st.columns(2)

    with col1:
        plan_button = st.button("📋 Create & Review Snippets", disabled=not feature_description)

    with col2:
        apply_button = st.button("⚡ Full Multi-Agent Review", type="primary", disabled=not feature_description)

    client = get_client()
    if not client:
        return

    if plan_button or apply_button:
        # Step 1: Editor Claude creates snippets
        st.subheader("🔧 Step 1: Editor Claude Creating Snippets...")
        with st.spinner("Editor analyzing code and creating edit plan..."):
            snippets = create_edit_snippets(client, current_code, feature_description, edit_rules)

        if not snippets.get("snippets"):
            st.error("Failed to create edit snippets")
            return

        # Display snippets
        st.success(f"✅ Created {len(snippets['snippets'])} edit snippet(s)")
        st.write(f"**Analysis:** {snippets.get('analysis', 'N/A')}")

        with st.expander("📝 View Edit Snippets", expanded=True):
            for i, snippet in enumerate(snippets["snippets"]):
                st.markdown(f"**Snippet {i+1}:** {snippet.get('location', 'Unknown location')}")
                st.markdown(f"- Action: `{snippet.get('action', 'unknown')}`")
                st.markdown(f"- Reason: {snippet.get('reason', 'N/A')}")
                if snippet.get("new_code"):
                    st.code(snippet["new_code"], language="python")
                st.divider()

        if plan_button and not apply_button:
            st.info("👆 Click 'Full Multi-Agent Review' to have judges review and apply these changes")
            # Store snippets in session state for later use
            st.session_state.pending_snippets = snippets
            st.session_state.pending_code = current_code
            st.session_state.pending_feature = feature_description
            st.session_state.pending_project = project_name
            return

        # Step 2: Two judges review independently
        st.subheader("⚖️ Step 2: Judge Review (2 Independent Reviewers)")

        col_j1, col_j2 = st.columns(2)

        with col_j1:
            with st.spinner("Judge 1 reviewing..."):
                judge1_result = judge_snippets(client, current_code, feature_description, snippets, 1)

        with col_j2:
            with st.spinner("Judge 2 reviewing..."):
                judge2_result = judge_snippets(client, current_code, feature_description, snippets, 2)

        # Display judge verdicts
        with col_j1:
            verdict1 = judge1_result.get("overall_verdict", "ERROR")
            icon1 = "✅" if verdict1 == "APPROVE" else "⚠️" if verdict1 == "NEEDS_REVISION" else "❌"
            st.markdown(f"### {icon1} Judge 1: {verdict1}")
            st.write(judge1_result.get("summary", "No summary"))
            confidence1 = judge1_result.get("confidence", 0)
            st.progress(confidence1, text=f"Confidence: {confidence1:.0%}")

        with col_j2:
            verdict2 = judge2_result.get("overall_verdict", "ERROR")
            icon2 = "✅" if verdict2 == "APPROVE" else "⚠️" if verdict2 == "NEEDS_REVISION" else "❌"
            st.markdown(f"### {icon2} Judge 2: {verdict2}")
            st.write(judge2_result.get("summary", "No summary"))
            confidence2 = judge2_result.get("confidence", 0)
            st.progress(confidence2, text=f"Confidence: {confidence2:.0%}")

        # Step 3: Voting
        st.subheader("🗳️ Step 3: Vote Tally")

        approvals = sum(1 for v in [verdict1, verdict2] if v == "APPROVE")
        rejections = sum(1 for v in [verdict1, verdict2] if v == "REJECT")
        revisions = sum(1 for v in [verdict1, verdict2] if v == "NEEDS_REVISION")

        st.write(f"- ✅ Approvals: {approvals}")
        st.write(f"- ⚠️ Needs Revision: {revisions}")
        st.write(f"- ❌ Rejections: {rejections}")

        # Determine outcome
        if rejections >= 2:
            st.error("❌ **REJECTED** - Both judges rejected the changes. Please revise your feature description.")
            add_log(f"Edit rejected by judges: {feature_description[:30]}...")
            return

        proceed = approvals >= 1 or (approvals + revisions >= 2 and rejections == 0)

        if proceed:
            st.success("✅ **APPROVED** - Proceeding with changes (incorporating feedback)")

            # Step 4: Apply vetted changes
            st.subheader("🚀 Step 4: Applying Vetted Changes")

            judge_feedback = [judge1_result, judge2_result]

            with st.spinner("Editor Claude applying approved changes..."):
                new_code = apply_vetted_snippets(client, current_code, snippets, judge_feedback)

            if new_code and new_code != current_code:
                # Save the updated code
                project_dir = PROJECTS_DIR / project_name
                project_dir.mkdir(exist_ok=True)

                # Backup original
                backup_file = project_dir / f"app_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py"
                backup_file.write_text(current_code, encoding="utf-8")

                # Write new code
                app_file = project_dir / "app.py"
                app_file.write_text(new_code, encoding="utf-8")

                save_project_state(project_name, {
                    "name": project_name,
                    "description": feature_description,
                    "mode": "edit",
                    "files": ["app.py"],
                    "review": {
                        "judge1": verdict1,
                        "judge2": verdict2,
                        "snippets_count": len(snippets["snippets"]),
                    }
                })

                st.success("✅ Changes applied successfully!")
                add_log(f"Multi-agent edit: {feature_description[:50]}...")

                with st.expander("View updated code"):
                    st.code(new_code, language="python")

                st.session_state.current_project = project_name
                st.session_state.status = "ready_to_test"
            else:
                st.warning("⚠️ No changes were made to the code")
        else:
            st.warning("⚠️ **NEEDS REVISION** - Please refine your feature description based on judge feedback")


# =============================================================================
# TEST MODE - Test existing app
# =============================================================================

def analyze_code_with_claude(client, code: str, test_steps: str, previous_issues: list = None) -> dict:
    """Use Claude to analyze code for issues."""

    previous_context = ""
    if previous_issues:
        previous_context = f"""
IMPORTANT: These issues were identified in a previous analysis.
Check if they are ACTUALLY FIXED now. Don't report them again if fixed:
{json.dumps(previous_issues, indent=2)}
"""

    prompt = f"""You are a senior Python developer and QA engineer. Analyze this Streamlit app code for:

1. **Syntax Errors** - Any code that won't run
2. **Logic Bugs** - Incorrect behavior, edge cases
3. **Security Issues** - SQL injection, XSS, exposed secrets
4. **Best Practices** - Missing error handling, poor UX
5. **Test Scenarios** - Based on the test steps provided
{previous_context}
CODE TO ANALYZE:
```python
{code}
```

TEST STEPS TO VERIFY:
{test_steps}

Respond in this exact JSON format:
{{
    "syntax_valid": true/false,
    "overall_score": 0-100,
    "issues": [
        {{
            "id": "unique_issue_id",
            "severity": "critical|high|medium|low",
            "category": "syntax|logic|security|best_practice",
            "line": "approximate line number or 'N/A'",
            "description": "What's wrong",
            "fix": "How to fix it",
            "code_snippet": "The specific code to change"
        }}
    ],
    "test_results": [
        {{
            "step": "Test step description",
            "status": "pass|fail|warning",
            "notes": "Details"
        }}
    ],
    "summary": "Overall assessment"
}}

Be specific about what code to change. Include actual code snippets."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.content[0].text
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        st.error(f"Analysis error: {e}")

    return {"syntax_valid": False, "overall_score": 0, "issues": [], "summary": "Analysis failed"}


def auto_fix_single_issue(client, code: str, issue: dict) -> tuple[str, bool]:
    """Fix ONE specific issue at a time. Returns (new_code, was_changed)."""
    prompt = f"""Fix ONLY this specific issue in the code. Make the minimal change needed.

ISSUE TO FIX:
- Severity: {issue.get('severity', 'unknown')}
- Category: {issue.get('category', 'unknown')}
- Description: {issue.get('description', 'unknown')}
- Suggested Fix: {issue.get('fix', 'unknown')}
- Code to change: {issue.get('code_snippet', 'N/A')}

CURRENT CODE:
```python
{code}
```

RULES:
1. Only fix THIS ONE issue
2. Make minimal changes
3. Don't refactor or improve other parts
4. Keep all existing functionality
5. Return the COMPLETE code with just this fix applied

Return ONLY the complete Python code, no explanations."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.content[0].text

        if "```python" in result:
            result = result.split("```python")[1].split("```")[0]
        elif "```" in result:
            result = result.split("```")[1].split("```")[0]

        new_code = result.strip()
        was_changed = new_code != code and len(new_code) > 100
        return new_code, was_changed
    except Exception as e:
        st.error(f"Fix error: {e}")
        return code, False


def format_analysis_text(analysis: dict, loop_num: int) -> str:
    """Format analysis results as copyable text."""
    lines = []
    lines.append(f"=" * 60)
    lines.append(f"ANALYSIS LOOP {loop_num}")
    lines.append(f"=" * 60)
    lines.append(f"Score: {analysis.get('overall_score', 0)}/100")
    lines.append(f"Syntax Valid: {analysis.get('syntax_valid', False)}")
    lines.append("")

    issues = analysis.get("issues", [])
    if issues:
        lines.append(f"ISSUES FOUND ({len(issues)}):")
        lines.append("-" * 40)
        for i, issue in enumerate(issues, 1):
            lines.append(f"\n[{issue.get('severity', 'unknown').upper()}] Issue {i}:")
            lines.append(f"  Category: {issue.get('category', 'N/A')}")
            lines.append(f"  Line: {issue.get('line', 'N/A')}")
            lines.append(f"  Description: {issue.get('description', 'N/A')}")
            lines.append(f"  Fix: {issue.get('fix', 'N/A')}")
            if issue.get('code_snippet'):
                lines.append(f"  Code: {issue.get('code_snippet', '')}")

    lines.append("")
    test_results = analysis.get("test_results", [])
    if test_results:
        lines.append("TEST RESULTS:")
        lines.append("-" * 40)
        for test in test_results:
            status = test.get("status", "unknown").upper()
            lines.append(f"  [{status}] {test.get('step', 'Unknown')}")
            lines.append(f"    Notes: {test.get('notes', '')}")

    lines.append("")
    lines.append(f"SUMMARY: {analysis.get('summary', 'N/A')}")

    return "\n".join(lines)


# =============================================================================
# TEST MODE HELPER FUNCTIONS
# =============================================================================

def _render_score_indicator(score: int) -> None:
    """Display score with appropriate color and message."""
    if score >= 90:
        st.success(f"✅ Score: {score}/100 - Excellent!")
    elif score >= 70:
        st.warning(f"⚠️ Score: {score}/100 - Needs improvement")
    else:
        st.error(f"❌ Score: {score}/100 - Significant issues")
    st.progress(score / 100)


def _render_issues_list(analysis: dict, loop_count: int, fixed_issue_ids: set) -> list:
    """
    Display issues with expand/copy buttons.
    Returns sorted issues list for further processing.
    """
    issues = analysis.get("issues", [])
    if not issues:
        return []

    # Action buttons row
    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
    with col_btn1:
        expand_all = st.checkbox("📂 Expand All", key=f"expand_{loop_count}")
    with col_btn2:
        copy_text = format_analysis_text(analysis, loop_count)
        st.download_button(
            "📋 Copy All",
            copy_text,
            file_name=f"analysis_loop_{loop_count}.txt",
            mime="text/plain",
            key=f"copy_{loop_count}"
        )

    st.write(f"**Found {len(issues)} issue(s):**")

    # Sort by severity (critical first)
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_issues = sorted(issues, key=lambda x: severity_order.get(x.get("severity", "low"), 4))

    # Display each issue
    severity_icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}
    for idx, issue in enumerate(sorted_issues):
        severity = issue.get("severity", "low")
        icon = severity_icons.get(severity, "⚪")
        issue_id = issue.get("id", f"issue_{idx}")
        fixed_marker = " (STILL PRESENT)" if issue_id in fixed_issue_ids else ""
        description_preview = issue.get('description', 'Unknown')[:50]

        with st.expander(f"{icon} [{severity.upper()}] {description_preview}...{fixed_marker}", expanded=expand_all):
            st.write(f"**Category:** {issue.get('category', 'N/A')}")
            st.write(f"**Line:** {issue.get('line', 'N/A')}")
            st.write(f"**Description:** {issue.get('description', 'N/A')}")
            st.write(f"**Fix:** {issue.get('fix', 'N/A')}")
            if issue.get('code_snippet'):
                st.code(issue.get('code_snippet', ''), language="python")

    return sorted_issues


def _render_test_results(test_results: list) -> None:
    """Display test results with status icons."""
    if not test_results:
        return

    st.write("**Test Results:**")
    status_icons = {"pass": "✅", "fail": "❌", "warning": "⚠️"}
    for test in test_results:
        status = test.get("status", "unknown")
        icon = status_icons.get(status, "❓")
        st.write(f"{icon} {test.get('step', 'Unknown')} - {test.get('notes', '')}")


def _should_stop_analysis(score: int, issues: list, target_score: int,
                          run_all_loops: bool, loop_count: int, max_loops: int) -> tuple:
    """
    Determine if analysis loop should stop.
    Returns: (should_stop, message, new_status)
    """
    critical_issues = [i for i in issues if i.get("severity") in ["critical", "high"]]

    # Check if passed target (unless run_all_loops is enabled)
    if not run_all_loops and score >= target_score and not critical_issues:
        return (True, f"🎉 Code passed! Score {score} >= target {target_score}", "passed")

    # Check if completed all loops
    if run_all_loops and loop_count >= max_loops:
        status = "passed" if score >= target_score else None
        return (True, f"📊 Completed all {max_loops} loops. Final score: {score}", status)

    return (False, None, None)


def _apply_single_issue_fix(client, code: str, sorted_issues: list,
                            fixed_issue_ids: set, app_file: Path, loop_count: int) -> tuple:
    """
    Fix the most critical issue only.
    Returns: (new_code, was_changed, issue_fixed)
    """
    # Try to fix most critical issue first
    for attempt_idx, issue_to_fix in enumerate(sorted_issues[:2]):  # Try top 2 issues max
        severity = issue_to_fix.get('severity', 'unknown').upper()
        description = issue_to_fix.get('description', '')[:50]

        if attempt_idx == 0:
            st.info(f"🔧 Fixing most critical issue: [{severity}] {description}...")
        else:
            st.warning("⚠️ Could not apply fix for previous issue. Trying next...")

        with st.spinner("Claude fixing this specific issue..."):
            fixed_code, was_changed = auto_fix_single_issue(client, code, issue_to_fix)

        if was_changed:
            fixed_issue_ids.add(issue_to_fix.get("id", f"issue_{attempt_idx}"))
            app_file.write_text(fixed_code, encoding="utf-8")
            add_log(f"Applied fix (loop {loop_count}): {description}...")

            with st.expander("View fixed code"):
                st.code(fixed_code, language="python")

            st.success("✅ Fix applied, re-analyzing to verify...")
            return (fixed_code, True, issue_to_fix)

    return (code, False, None)


def _apply_all_issues_fix(client, code: str, issues: list,
                          app_file: Path, loop_count: int) -> tuple:
    """
    Fix all issues at once.
    Returns: (new_code, was_changed, issues_fixed)
    """
    st.info("🔧 Auto-fixing all issues...")

    prompt = f"""Fix ALL these issues in the code:

{json.dumps(issues, indent=2)}

CURRENT CODE:
```python
{code}
```

Return ONLY the complete fixed Python code."""

    with st.spinner("Claude fixing code..."):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=8000,
                messages=[{"role": "user", "content": prompt}]
            )
            result = response.content[0].text
            if "```python" in result:
                result = result.split("```python")[1].split("```")[0]
            fixed_code = result.strip()
        except Exception as e:
            st.error(f"Fix error: {e}")
            return (code, False, None)

    if fixed_code != code:
        app_file.write_text(fixed_code, encoding="utf-8")
        add_log(f"Applied fixes (loop {loop_count})")

        with st.expander("View fixed code"):
            st.code(fixed_code, language="python")

        st.success("✅ Fixes applied, re-analyzing...")
        return (fixed_code, True, issues)

    st.warning("No changes made by auto-fix")
    return (code, False, None)


def _render_export_section(selected_project: str, code_to_test: str,
                           all_analyses: list, loop_count: int) -> None:
    """Render the export/download section."""
    st.divider()
    st.subheader("📥 Export Results")

    # Fixed Code download section
    st.markdown("### 🔧 Fixed Code")
    st.success(f"Final code ready for download ({len(code_to_test)} characters)")

    col_code1, col_code2 = st.columns(2)
    with col_code1:
        st.download_button(
            "⬇️ DOWNLOAD FIXED CODE (.py)",
            code_to_test,
            file_name=f"{selected_project}_fixed.py",
            mime="text/x-python",
            type="primary"
        )
    with col_code2:
        line_count = len(code_to_test.split('\n'))
        with st.expander(f"📄 View Fixed Code ({line_count} lines)"):
            st.code(code_to_test, language="python")

    st.divider()

    # Reports section
    st.markdown("### 📊 Analysis Reports")

    full_export = {
        "project": selected_project,
        "total_loops": loop_count,
        "final_status": st.session_state.status,
        "analyses": all_analyses,
        "final_code": code_to_test,
        "final_code_length": len(code_to_test),
    }

    col_exp1, col_exp2 = st.columns(2)
    with col_exp1:
        st.download_button(
            "📥 Full Report (JSON)",
            json.dumps(full_export, indent=2),
            file_name=f"{selected_project}_analysis_report.json",
            mime="application/json"
        )
    with col_exp2:
        full_text = f"STREAMTEST ANALYSIS REPORT\nProject: {selected_project}\n\n"
        for item in all_analyses:
            full_text += format_analysis_text(item["analysis"], item["loop"]) + "\n\n"
        full_text += "\n\n" + "=" * 60 + "\nFINAL FIXED CODE:\n" + "=" * 60 + "\n\n"
        full_text += code_to_test

        st.download_button(
            "📥 Full Report (TXT)",
            full_text,
            file_name=f"{selected_project}_analysis_report.txt",
            mime="text/plain"
        )


# =============================================================================
# TEST MODE - Main function
# =============================================================================

def test_mode():
    """Test pre-built app with Claude analysis."""
    st.header("🧪 Test Only")

    st.markdown("""
    **Automated Code Analysis & Fix Loop**:
    1. Claude analyzes your code for issues
    2. Shows problems with severity ratings
    3. Fixes ONE issue at a time (most critical first)
    4. Re-analyzes to verify fix worked
    """)

    # Project selection
    existing_projects = list_projects()

    col1, col2 = st.columns(2)

    with col1:
        selected_project = st.selectbox(
            "Select project to test",
            [""] + existing_projects
        )

    with col2:
        uploaded_file = st.file_uploader("Or upload .py file", type=["py"])

    if uploaded_file:
        project_name = uploaded_file.name.replace(".py", "")
        project_dir = PROJECTS_DIR / project_name
        project_dir.mkdir(exist_ok=True)

        code = uploaded_file.read().decode("utf-8")
        (project_dir / "app.py").write_text(code, encoding="utf-8")

        st.success(f"Uploaded to: {project_dir}/app.py")
        selected_project = project_name

    if not selected_project:
        st.info("Select a project or upload a file to test")
        return

    project_dir = PROJECTS_DIR / selected_project
    app_file = project_dir / "app.py"

    if not app_file.exists():
        st.error(f"No app.py found in {project_dir}")
        return

    current_code = app_file.read_text(encoding="utf-8")

    with st.expander("View code"):
        st.code(current_code, language="python")

    # Test configuration
    st.subheader("Test Configuration")

    test_steps = st.text_area(
        "Test scenarios (one per line)",
        value="Page loads without errors\nAll UI elements render correctly\nButtons and inputs are functional\nNo security vulnerabilities",
        height=100
    )

    # Row 1: Loops and target score
    col_a, col_b = st.columns(2)
    with col_a:
        max_loops = st.slider("Max fix attempts", 1, 15, 5)
    with col_b:
        target_score = st.slider("Target score to stop", 80, 100, 90, help="Stop when this score is reached (unless 'Run all loops' is checked)")

    # Row 2: Checkboxes
    col_c, col_d, col_e = st.columns(3)
    with col_c:
        auto_fix = st.checkbox("Auto-fix issues", value=True)
    with col_d:
        fix_one_at_time = st.checkbox("Fix one at a time", value=True, help="Fixes most critical issue first, then re-analyzes")
    with col_e:
        run_all_loops = st.checkbox("Run all loops", value=False, help="Ignore target score, run all loops regardless")

    if st.button("🚀 Start Analysis", type="primary"):
        client = get_client()
        if not client:
            return

        st.session_state.current_project = selected_project
        st.session_state.status = "testing"
        add_log(f"Starting test: {selected_project}")

        # Store all analysis results for export
        all_analyses = []
        fixed_issue_ids = set()

        code_to_test = current_code
        loop_count = 0
        previous_issues = []

        while loop_count < max_loops:
            loop_count += 1
            st.subheader(f"📊 Analysis Loop {loop_count}/{max_loops}")

            # Run analysis
            with st.spinner(f"Claude analyzing code (attempt {loop_count})..."):
                analysis = analyze_code_with_claude(
                    client, code_to_test, test_steps,
                    previous_issues if loop_count > 1 else None
                )
            all_analyses.append({"loop": loop_count, "analysis": analysis})

            # Display results
            score = analysis.get("overall_score", 0)
            issues = analysis.get("issues", [])

            _render_score_indicator(score)
            sorted_issues = _render_issues_list(analysis, loop_count, fixed_issue_ids)
            _render_test_results(analysis.get("test_results", []))
            st.write(f"**Summary:** {analysis.get('summary', 'N/A')}")

            # Store for later download
            st.session_state.final_fixed_code = code_to_test
            st.session_state.final_project_name = selected_project

            # Check if we should stop
            should_stop, message, new_status = _should_stop_analysis(
                score, issues, target_score, run_all_loops, loop_count, max_loops
            )
            if should_stop:
                if new_status == "passed":
                    st.success(message)
                    st.session_state.status = "passed"
                    add_log(f"Test PASSED: {selected_project} (score: {score})")
                else:
                    st.info(message)
                    if new_status:
                        st.session_state.status = new_status
                break

            # Apply fixes if enabled
            if not auto_fix:
                st.info("Auto-fix disabled. Enable to automatically fix issues.")
                break

            if not issues or loop_count >= max_loops:
                break

            if fix_one_at_time:
                new_code, was_changed, issue_fixed = _apply_single_issue_fix(
                    client, code_to_test, sorted_issues,
                    fixed_issue_ids, app_file, loop_count
                )
                if was_changed:
                    code_to_test = new_code
                    previous_issues = [issue_fixed]
                    continue
                break
            else:
                new_code, was_changed, issues_fixed = _apply_all_issues_fix(
                    client, code_to_test, issues, app_file, loop_count
                )
                if was_changed:
                    code_to_test = new_code
                    previous_issues = issues_fixed
                    continue
                break

        # Final status
        if st.session_state.status != "passed":
            st.session_state.status = "failed"
            add_log(f"Test completed with issues: {selected_project}")

        # Render export section
        _render_export_section(selected_project, code_to_test, all_analyses, loop_count)


# =============================================================================
# SETTINGS MODE - Edit prompts and configuration
# =============================================================================

def settings_mode():
    """Settings page for editing prompts and configuration."""
    st.header("⚙️ Settings")

    st.markdown("""
    **Customize the AI prompts** that control how StreamTest analyzes and fixes code.
    These prompts are the "personality" that guides Claude's behavior.
    """)

    # Analysis Prompt
    st.subheader("📊 Analysis Prompt")
    st.caption("This prompt tells Claude how to analyze code for issues")

    analysis_prompt = st.text_area(
        "Analysis Prompt",
        value=st.session_state.analysis_prompt,
        height=200,
        key="edit_analysis_prompt"
    )

    col_a1, col_a2 = st.columns([1, 4])
    with col_a1:
        if st.button("💾 Save", key="save_analysis"):
            st.session_state.analysis_prompt = analysis_prompt
            st.success("Analysis prompt saved!")
    with col_a2:
        if st.button("🔄 Reset to Default", key="reset_analysis"):
            st.session_state.analysis_prompt = DEFAULT_ANALYSIS_PROMPT
            st.success("Reset to default!")
            st.rerun()

    st.divider()

    # Fix Prompt
    st.subheader("🔧 Fix Prompt")
    st.caption("This prompt tells Claude how to fix individual issues")

    fix_prompt = st.text_area(
        "Fix Prompt",
        value=st.session_state.fix_prompt,
        height=200,
        key="edit_fix_prompt"
    )

    col_f1, col_f2 = st.columns([1, 4])
    with col_f1:
        if st.button("💾 Save", key="save_fix"):
            st.session_state.fix_prompt = fix_prompt
            st.success("Fix prompt saved!")
    with col_f2:
        if st.button("🔄 Reset to Default", key="reset_fix"):
            st.session_state.fix_prompt = DEFAULT_FIX_PROMPT
            st.success("Reset to default!")
            st.rerun()

    st.divider()

    # Judge Prompt
    st.subheader("⚖️ Judge Prompt (Multi-Agent Review)")
    st.caption("This prompt tells the Judge Claudes how to review code changes")

    judge_prompt = st.text_area(
        "Judge Prompt",
        value=st.session_state.judge_prompt,
        height=200,
        key="edit_judge_prompt"
    )

    col_j1, col_j2 = st.columns([1, 4])
    with col_j1:
        if st.button("💾 Save", key="save_judge"):
            st.session_state.judge_prompt = judge_prompt
            st.success("Judge prompt saved!")
    with col_j2:
        if st.button("🔄 Reset to Default", key="reset_judge"):
            st.session_state.judge_prompt = DEFAULT_JUDGE_PROMPT
            st.success("Reset to default!")
            st.rerun()

    st.divider()

    # Tips section
    with st.expander("💡 Tips for Writing Effective Prompts"):
        st.markdown("""
        **What makes prompts effective:**

        1. **Clear Role Definition**
           - "You are a senior Python developer..."
           - "You are a security expert..."

        2. **Explicit Rules (MOST IMPORTANT)**
           - "NEVER do X"
           - "ALWAYS do Y"
           - "If Z happens, do W"

        3. **Structured Output Format**
           - "Respond in this exact JSON format:..."
           - Specify exact field names and types

        4. **Examples**
           - Show good and bad examples
           - "Here's what a good response looks like:..."

        5. **Priority Ordering**
           - "Most important: X. Second priority: Y..."

        6. **Negative Examples**
           - "Do NOT do this: [example of bad output]"

        **Why Claude Code follows instructions better than ChatGPT:**
        - System prompts are heavily weighted
        - Trained specifically for instruction-following
        - Responds well to NEVER/ALWAYS rules
        """)


# =============================================================================
# SIDEBAR - Status, Logs, Settings
# =============================================================================

def render_sidebar():
    """Render sidebar with status and logs."""
    with st.sidebar:
        st.title("StreamTest")

        # Mode selection
        mode = st.radio(
            "Mode",
            ["BUILD", "EDIT", "TEST", "SETTINGS"],
            index=["BUILD", "EDIT", "TEST", "SETTINGS"].index(st.session_state.mode) if st.session_state.mode in ["BUILD", "EDIT", "TEST", "SETTINGS"] else 2
        )
        st.session_state.mode = mode

        st.divider()

        # Status
        st.subheader("Status")
        status_colors = {
            "idle": "🔵",
            "building": "🟡",
            "testing": "🟡",
            "ready_to_test": "🟢",
            "passed": "✅",
            "failed": "🔴"
        }
        st.write(f"{status_colors.get(st.session_state.status, '⚪')} {st.session_state.status.upper()}")

        if st.session_state.current_project:
            st.write(f"📁 Project: {st.session_state.current_project}")

        st.divider()

        # Logs
        st.subheader("Recent Logs")
        for log in st.session_state.logs[-10:]:
            st.text(log)

        if st.button("Clear Logs"):
            st.session_state.logs = []

        st.divider()

        # Export/Import
        st.subheader("Data")

        if st.button("📥 Export State"):
            state = {
                "projects": list_projects(),
                "logs": st.session_state.logs,
                "current_project": st.session_state.current_project,
            }
            st.download_button(
                "Download JSON",
                json.dumps(state, indent=2),
                "streamtest_state.json",
                "application/json"
            )

        with st.expander("📤 Import State"):
            uploaded_state = st.file_uploader("Upload JSON", type=["json"], key="import_state")
            if uploaded_state:
                try:
                    state = json.loads(uploaded_state.read().decode("utf-8"))
                    st.session_state.logs = state.get("logs", [])
                    st.success("State imported!")
                except Exception as e:
                    st.error(f"Error importing: {e}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    st.set_page_config(
        page_title="StreamTest Dashboard",
        page_icon="🧪",
        layout="wide"
    )

    init_session_state()
    render_sidebar()

    # Main content based on mode
    if st.session_state.mode == "BUILD":
        build_mode()
    elif st.session_state.mode == "EDIT":
        edit_mode()
    elif st.session_state.mode == "SETTINGS":
        settings_mode()
    else:
        test_mode()


if __name__ == "__main__":
    main()
