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

CLAUDE_MODEL = "claude-sonnet-4-20250514"


def init_session_state():
    """Initialize session state variables."""
    defaults = {
        "mode": "TEST",
        "current_project": None,
        "logs": [],
        "loop_count": 0,
        "status": "idle",
        "planned_changes": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def get_client():
    """Get Anthropic client."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        st.error("ANTHROPIC_API_KEY not set in .env file!")
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
            prompt = f"""You are an expert Python/Streamlit developer. Create a complete, working Streamlit app based on this description:

DESCRIPTION:
{description}

RULES:
{build_rules if build_rules else "- Use Streamlit for UI\n- Keep code clean and simple\n- Handle errors gracefully"}

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

def analyze_code_with_claude(client, code: str, test_steps: str) -> dict:
    """Use Claude to analyze code for issues."""
    prompt = f"""You are a senior Python developer and QA engineer. Analyze this Streamlit app code for:

1. **Syntax Errors** - Any code that won't run
2. **Logic Bugs** - Incorrect behavior, edge cases
3. **Security Issues** - SQL injection, XSS, exposed secrets
4. **Best Practices** - Missing error handling, poor UX
5. **Test Scenarios** - Based on the test steps provided

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
            "severity": "critical|high|medium|low",
            "category": "syntax|logic|security|best_practice",
            "line": "approximate line number or 'N/A'",
            "description": "What's wrong",
            "fix": "How to fix it"
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
}}"""

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


def auto_fix_issues(client, code: str, issues: list) -> str:
    """Have Claude fix the identified issues."""
    prompt = f"""Fix the following issues in this code. Return ONLY the corrected Python code.

CURRENT CODE:
```python
{code}
```

ISSUES TO FIX:
{json.dumps(issues, indent=2)}

Return the complete fixed code, no explanations."""

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

        return result.strip()
    except Exception as e:
        st.error(f"Fix error: {e}")
        return code


def test_mode():
    """Test pre-built app with Claude analysis."""
    st.header("🧪 Test Only")

    st.markdown("""
    **Automated Code Analysis & Fix Loop**:
    1. Claude analyzes your code for issues
    2. Shows problems with severity ratings
    3. Auto-fixes issues if requested
    4. Re-analyzes until passing
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

    col_a, col_b = st.columns(2)
    with col_a:
        max_loops = st.slider("Max fix attempts", 1, 10, 5)
    with col_b:
        auto_fix = st.checkbox("Auto-fix issues", value=True)

    if st.button("🚀 Start Analysis", type="primary"):
        client = get_client()
        if not client:
            return

        st.session_state.current_project = selected_project
        st.session_state.status = "testing"
        add_log(f"Starting test: {selected_project}")

        code_to_test = current_code
        loop_count = 0

        while loop_count < max_loops:
            loop_count += 1
            st.subheader(f"📊 Analysis Loop {loop_count}/{max_loops}")

            with st.spinner(f"Claude analyzing code (attempt {loop_count})..."):
                analysis = analyze_code_with_claude(client, code_to_test, test_steps)

            # Display score
            score = analysis.get("overall_score", 0)
            if score >= 90:
                st.success(f"✅ Score: {score}/100 - Excellent!")
            elif score >= 70:
                st.warning(f"⚠️ Score: {score}/100 - Needs improvement")
            else:
                st.error(f"❌ Score: {score}/100 - Significant issues")

            st.progress(score / 100)

            # Display issues
            issues = analysis.get("issues", [])
            if issues:
                st.write(f"**Found {len(issues)} issue(s):**")

                for issue in issues:
                    severity = issue.get("severity", "low")
                    icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(severity, "⚪")

                    with st.expander(f"{icon} [{severity.upper()}] {issue.get('description', 'Unknown')[:50]}..."):
                        st.write(f"**Category:** {issue.get('category', 'N/A')}")
                        st.write(f"**Line:** {issue.get('line', 'N/A')}")
                        st.write(f"**Description:** {issue.get('description', 'N/A')}")
                        st.write(f"**Fix:** {issue.get('fix', 'N/A')}")

            # Display test results
            test_results = analysis.get("test_results", [])
            if test_results:
                st.write("**Test Results:**")
                for test in test_results:
                    status = test.get("status", "unknown")
                    icon = {"pass": "✅", "fail": "❌", "warning": "⚠️"}.get(status, "❓")
                    st.write(f"{icon} {test.get('step', 'Unknown')} - {test.get('notes', '')}")

            st.write(f"**Summary:** {analysis.get('summary', 'N/A')}")

            # Check if passing
            critical_issues = [i for i in issues if i.get("severity") in ["critical", "high"]]

            if score >= 90 and not critical_issues:
                st.success("🎉 Code passed all checks!")
                st.session_state.status = "passed"
                add_log(f"Test PASSED: {selected_project} (score: {score})")
                break

            # Auto-fix if enabled
            if auto_fix and issues and loop_count < max_loops:
                st.info("🔧 Auto-fixing issues...")

                with st.spinner("Claude fixing code..."):
                    fixed_code = auto_fix_issues(client, code_to_test, issues)

                if fixed_code != code_to_test:
                    code_to_test = fixed_code

                    # Save fixed code
                    app_file.write_text(fixed_code, encoding="utf-8")
                    add_log(f"Applied fixes (loop {loop_count})")

                    with st.expander("View fixed code"):
                        st.code(fixed_code, language="python")

                    st.success("✅ Fixes applied, re-analyzing...")
                    continue
                else:
                    st.warning("No changes made by auto-fix")
                    break
            else:
                if not auto_fix:
                    st.info("Auto-fix disabled. Enable to automatically fix issues.")
                break

        # Final status
        if st.session_state.status != "passed":
            st.session_state.status = "failed"
            add_log(f"Test completed with issues: {selected_project}")


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
            ["BUILD", "EDIT", "TEST"],
            index=["BUILD", "EDIT", "TEST"].index(st.session_state.mode)
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
    else:
        test_mode()


if __name__ == "__main__":
    main()
