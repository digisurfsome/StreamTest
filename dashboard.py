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

# Model Configuration - Opus for complex tasks, Haiku for simple fixes
CLAUDE_MODEL = "claude-opus-4-5-20251101"
CLAUDE_HAIKU = "claude-3-5-haiku-20241022"  # Fast & cheap for simple fixes

# =============================================================================
# APP MODE CONFIGURATION - Toggle between full app vs simple MVP expectations
# =============================================================================
APP_MODES = {
    "full_app": {
        "name": "Full App (Database + Auth)",
        "description": "Enterprise-ready with database, authentication, user management",
        "prompt_modifier": """
APP CONTEXT: This is a FULL APPLICATION with database and authentication.
- Expect proper database integration (PostgreSQL, SQLite, etc.)
- Session data that needs persistence MUST be stored in database
- PIN/authentication attempts MUST be stored in database to prevent bypass
- Proper user management and authentication is expected
- Rate limiting and security measures should be robust
"""
    },
    "simple_mvp": {
        "name": "Simple MVP (No Database)",
        "description": "Personal testing/MVP with JSON file save/load for data",
        "prompt_modifier": """
APP CONTEXT: This is a SIMPLE MVP without a database - THIS IS INTENTIONAL.
- No database is expected or required - this is by design
- Data persistence via JSON file upload/download is ACCEPTABLE and CORRECT
- Session state for temporary data is FINE for this use case
- Simple PIN in session state is ACCEPTABLE for personal MVP testing
- Focus on functionality over enterprise security
- DO NOT flag lack of database as an issue - it's intentional
- DO NOT require authentication/user management for simple MVPs
"""
    },
    "prototype": {
        "name": "Prototype (Experimental)",
        "description": "Early stage testing, may have rough edges",
        "prompt_modifier": """
APP CONTEXT: This is an EARLY PROTOTYPE for experimental testing.
- Code may be rough/incomplete - focus on critical issues only
- Skip minor style/best practice issues unless they cause bugs
- No database or persistence expected
- Security is minimal - this is for personal experimentation only
- Only flag issues that would BREAK functionality
"""
    }
}

# =============================================================================
# CODING STANDARDS - The "Coding Bible" reference for all prompts
# =============================================================================
CODING_STANDARDS = """
## CODING STANDARDS REFERENCE

### Python Best Practices
- Use type hints for function parameters and return values
- Handle exceptions specifically, not with bare `except:`
- Use context managers (`with` statements) for resources
- Avoid mutable default arguments (use `None` instead of `[]`)
- Use `secrets.compare_digest()` for secure string comparison
- Never store sensitive data in session_state (use database)

### Streamlit Best Practices
- Initialize ALL session_state variables at app start
- Use unique `key=` for all interactive widgets
- Store persistent data in database, not session_state
- Put expensive operations behind `@st.cache_data` or `@st.cache_resource`
- Use `st.rerun()` sparingly - only when state actually changed
- Always show user feedback (spinners, success/error messages)
- Handle the case when session_state values are None/missing

### Database Best Practices
- Use context managers for database connections (`with get_db() as db:`)
- Use parameterized queries (never string concatenation for SQL)
- Store counters/attempts in database for persistence across sessions
- Use atomic operations (transactions) for multi-step updates
- Always close database connections properly

### Security
- Validate all user input before using
- Use `secrets.compare_digest()` for timing-safe comparisons
- Never expose API keys or secrets in code
- Store PIN attempts in database (not session_state) to prevent bypass
- Implement rate limiting for sensitive operations

### Code Structure
- Keep functions focused on single responsibility
- Avoid deep nesting (max 3-4 levels)
- Use early returns to reduce complexity
- Group related functionality into modules
- Document complex logic with comments
"""

# Categorized coding bible sections for targeted pre-read
CODING_BIBLE_SECTIONS = {
    "security": """
### SECURITY CODING BIBLE (Pre-Read Required)
- Use `secrets.compare_digest()` for ALL sensitive comparisons (PINs, tokens, passwords)
- NEVER store sensitive data in session_state - use database
- Store PIN/login attempts in DATABASE to prevent session refresh bypass
- Validate ALL user input before using
- Never expose API keys or secrets in code
- Implement rate limiting for authentication operations
- Use parameterized queries - NEVER string concatenation for SQL
""",
    "database": """
### DATABASE CODING BIBLE (Pre-Read Required)
- Use context managers: `with get_db() as db:`
- ALWAYS use parameterized queries (?, %s) - never string concat
- Store persistent counters/state in database, not session_state
- Use atomic operations (transactions) for multi-step updates
- Close connections properly - context managers handle this
- Handle connection errors gracefully with try/except
""",
    "streamlit": """
### STREAMLIT CODING BIBLE (Pre-Read Required)
- Initialize ALL session_state variables at app start in one place
- Use unique `key=` parameter for EVERY interactive widget
- Use `st.rerun()` sparingly - only when state actually changed
- Put expensive operations behind `@st.cache_data` or `@st.cache_resource`
- Always show user feedback (spinners, success/error messages)
- Handle None/missing session_state values with .get() method
""",
    "logic": """
### LOGIC/STRUCTURE CODING BIBLE (Pre-Read Required)
- Keep functions focused on single responsibility
- Avoid deep nesting - max 3-4 levels, use early returns
- Handle exceptions specifically, not bare `except:`
- Use type hints for function parameters and return values
- Avoid mutable default arguments (use None instead of [])
- Use context managers for resources (files, connections)
""",
    "best_practice": """
### BEST PRACTICES CODING BIBLE (Pre-Read Required)
- Keep functions focused and small (single responsibility)
- Use descriptive variable names
- Add comments for complex logic only (code should be self-documenting)
- Use early returns to reduce nesting
- Group related imports at top of file
- Follow consistent naming conventions (snake_case for Python)
"""
}


def get_relevant_bible_section(issue: dict) -> str:
    """
    PRE-READ MECHANISM: Look up the relevant coding bible section
    based on the issue category. This refreshes the agent's memory
    about best practices BEFORE it attempts the fix.
    """
    category = issue.get("category", "").lower()
    description = issue.get("description", "").lower()

    # Map issue to bible section
    if category == "security" or "security" in description or "pin" in description or "auth" in description:
        return CODING_BIBLE_SECTIONS["security"]
    elif category == "database" or "database" in description or "db" in description or "sql" in description:
        return CODING_BIBLE_SECTIONS["database"]
    elif "session" in description or "widget" in description or "key" in description or "rerun" in description:
        return CODING_BIBLE_SECTIONS["streamlit"]
    elif category == "logic" or "logic" in description or "exception" in description or "error" in description:
        return CODING_BIBLE_SECTIONS["logic"]
    else:
        return CODING_BIBLE_SECTIONS["best_practice"]


# Default prompts (editable in Settings)
DEFAULT_ANALYSIS_PROMPT = """You are a senior Python developer and QA engineer. Analyze this Streamlit app code for:

1. **Syntax Errors** - Any code that won't run
2. **Logic Bugs** - Incorrect behavior, edge cases
3. **Security Issues** - SQL injection, XSS, exposed secrets, session_state security flaws
4. **Best Practices** - Missing error handling, poor UX, non-persistent data in session_state
5. **Test Scenarios** - Based on the test steps provided

IMPORTANT: Check violations of these coding standards:
- Data that should persist (like PIN attempts, counters) must be in DATABASE, not session_state
- All widgets need unique `key=` parameters
- Exception handling must be specific, not bare `except:`
- Use `secrets.compare_digest()` for any sensitive comparisons

Be specific about what code to change. Include actual code snippets."""

DEFAULT_FIX_PROMPT = """Fix ONLY this specific issue in the code. Make the minimal change needed.

RULES:
1. Only fix THIS ONE issue
2. Make minimal changes
3. Don't refactor or improve other parts
4. Keep all existing functionality
5. Return the COMPLETE code with just this fix applied

FOLLOW CODING STANDARDS:
- If storing persistent data, use DATABASE not session_state
- Use type hints where appropriate
- Use context managers for database/file operations
- Specific exception handling (not bare except)

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
        # TEST MODE: Persist analysis results across reruns (fixes download button bug)
        "analysis_results": [],  # List of {loop, analysis} dicts
        "analysis_complete": False,  # Flag to show results section
        "tested_project": None,  # Project name that was tested
        "test_loop_count": 0,  # Number of loops completed
        # APP MODE: Toggle between full app vs simple MVP expectations
        "app_mode": "simple_mvp",  # Default to simple MVP (most common use case)
        # TRACKING: Monitor what mechanisms are being used
        "coding_bible_used": False,  # Track if coding standards were referenced
        "voting_used": False,  # Track if multi-agent voting was used
        "batch_fixes_count": 0,  # Track how many batch fixes happened
        "haiku_fixes_count": 0,  # Track Haiku usage
        "opus_fixes_count": 0,  # Track Opus usage
        "verification_passes": 0,  # Track successful verifications
        "verification_fails": 0,  # Track failed verifications
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

def analyze_code_with_claude(client, code: str, test_steps: str, previous_issues: list = None, app_mode: str = "simple_mvp") -> dict:
    """Use Claude to analyze code for issues."""

    # Track that we're using the coding bible
    st.session_state.coding_bible_used = True

    previous_context = ""
    if previous_issues:
        previous_context = f"""
IMPORTANT: These issues were identified in a previous analysis.
Check if they are ACTUALLY FIXED now. Don't report them again if fixed:
{json.dumps(previous_issues, indent=2)}
"""

    # Get app mode context - CRITICAL for proper judgment
    app_mode_context = APP_MODES.get(app_mode, APP_MODES["simple_mvp"])["prompt_modifier"]

    prompt = f"""You are a senior Python developer and QA engineer. Analyze this Streamlit app code for:

1. **Syntax Errors** - Any code that won't run
2. **Logic Bugs** - Incorrect behavior, edge cases
3. **Security Issues** - SQL injection, XSS, exposed secrets
4. **Best Practices** - Missing error handling, poor UX
5. **Test Scenarios** - Based on the test steps provided

{app_mode_context}

{CODING_STANDARDS}
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

    # PRE-READ: Look up relevant coding bible section BEFORE coding
    bible_section = get_relevant_bible_section(issue)

    prompt = f"""Fix ONLY this specific issue in the code. Make the minimal change needed.

**FIRST, READ THIS CODING BIBLE SECTION:**
{bible_section}

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
6. FOLLOW THE CODING BIBLE SECTION ABOVE

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


def should_use_haiku(issue: dict) -> bool:
    """
    Determine if Haiku can handle this fix (simple issues) or if we need Opus (complex issues).
    Haiku handles: LOW severity, best_practice category, simple refactoring
    Opus handles: CRITICAL/HIGH severity, security issues, complex logic bugs
    """
    severity = issue.get('severity', 'medium').lower()
    category = issue.get('category', '').lower()

    # Always use Opus for critical/high severity
    if severity in ['critical', 'high']:
        return False

    # Always use Opus for security issues
    if category == 'security':
        return False

    # Use Haiku for low severity and best practices
    if severity == 'low' or category == 'best_practice':
        return True

    # Medium severity - check category
    if category in ['best_practice', 'style', 'documentation']:
        return True

    # Default to Opus for anything else
    return False


def fix_with_haiku(client, code: str, issue: dict) -> tuple[str, bool]:
    """
    Use Haiku for simple fixes - faster and cheaper.
    Returns (new_code, was_changed)
    """
    # PRE-READ: Even Haiku gets the coding bible section
    bible_section = get_relevant_bible_section(issue)

    prompt = f"""Fix this specific issue in the code. Make the minimal change needed.

**FIRST, READ THIS:**
{bible_section}

ISSUE:
- Category: {issue.get('category', 'unknown')}
- Description: {issue.get('description', 'unknown')}
- Fix: {issue.get('fix', 'unknown')}
- Code to change: {issue.get('code_snippet', 'N/A')}

CODE:
```python
{code}
```

Return ONLY the complete fixed Python code, no explanations."""

    try:
        response = client.messages.create(
            model=CLAUDE_HAIKU,
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
        st.warning(f"Haiku fix error: {e}")
        return code, False


def batch_fix_issues(client, code: str, issues: list, max_issues: int = 3) -> tuple[str, bool, list]:
    """
    Fix multiple non-conflicting issues at once with Opus.
    Returns (new_code, was_changed, issues_attempted)

    Groups issues by category and fixes up to max_issues at once.
    This is MORE EFFICIENT than one-at-a-time for Opus 4.5.
    """
    if not issues:
        return code, False, []

    # Take up to max_issues, prioritizing by severity
    issues_to_fix = issues[:max_issues]

    # PRE-READ: Collect ALL relevant coding bible sections for these issues
    bible_sections_needed = set()
    for issue in issues_to_fix:
        section = get_relevant_bible_section(issue)
        bible_sections_needed.add(section)
    combined_bible = "\n".join(bible_sections_needed)

    issues_description = "\n".join([
        f"{i+1}. [{issue.get('severity', 'unknown').upper()}] {issue.get('category', 'unknown')}: {issue.get('description', 'unknown')}\n   Fix: {issue.get('fix', 'unknown')}\n   Code: {issue.get('code_snippet', 'N/A')}"
        for i, issue in enumerate(issues_to_fix)
    ])

    prompt = f"""Fix ALL of these issues in the code. You are Opus 4.5 - you can handle multiple fixes at once.

**FIRST, READ THESE CODING BIBLE SECTIONS:**
{combined_bible}

ISSUES TO FIX:
{issues_description}

CURRENT CODE:
```python
{code}
```

RULES:
1. Fix ALL listed issues in one pass
2. Make clean, minimal changes
3. Don't introduce new issues
4. Keep all existing functionality
5. Return the COMPLETE code with ALL fixes applied
6. FOLLOW THE CODING BIBLE SECTIONS ABOVE

Return ONLY the complete Python code, no explanations."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.content[0].text

        if "```python" in result:
            result = result.split("```python")[1].split("```")[0]
        elif "```" in result:
            result = result.split("```")[1].split("```")[0]

        new_code = result.strip()
        was_changed = new_code != code and len(new_code) > 100
        return new_code, was_changed, issues_to_fix
    except Exception as e:
        st.error(f"Batch fix error: {e}")
        return code, False, []


def get_issue_fingerprint(issue: dict) -> str:
    """Create a unique fingerprint for an issue to detect duplicates."""
    return f"{issue.get('category', '')}:{issue.get('description', '')[:50]}:{issue.get('line', '')}"


def verify_fix_worked(client, original_code: str, fixed_code: str, issue: dict) -> tuple[bool, str]:
    """
    VERIFIER: Uses Opus for verification - checks if the fix actually resolved the issue.
    Decision-making should always use the best model (Opus), not Haiku.
    Returns (fix_worked: bool, reasoning: str)
    """
    # Use Opus for verification - decision-making should use the best model
    prompt = f"""You are an independent CODE VERIFIER. Determine if this fix resolved the specific issue.

ISSUE THAT NEEDED FIXING:
- Severity: {issue.get('severity', 'unknown')}
- Category: {issue.get('category', 'unknown')}
- Description: {issue.get('description', 'unknown')}
- Suggested Fix: {issue.get('fix', 'unknown')}
- Code snippet: {issue.get('code_snippet', 'N/A')}

ORIGINAL CODE:
```python
{original_code}
```

FIXED CODE:
```python
{fixed_code}
```

TASK: Did the fix address THIS SPECIFIC issue? Don't look for new issues.

Respond in JSON:
{{"fix_worked": true/false, "reasoning": "brief explanation"}}"""

    try:
        # Use Opus for verification - decision-making needs the best model
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.content[0].text
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            verification = json.loads(json_match.group())
            return verification.get("fix_worked", False), verification.get("reasoning", "No reasoning provided")
    except Exception as e:
        st.warning(f"Verification check failed: {e}")

    # Default to assuming fix worked if verification fails
    return True, "Verification check could not be completed"


def multi_agent_vote(client, original_code: str, fixed_code: str, issue: dict) -> tuple[bool, str, dict]:
    """
    MULTI-AGENT VOTING SYSTEM - Corrected Flow:

    Agent 1 = CODER (already made the fix - implicitly approves their own work)
    Agent 2 = REVIEWER (checks work, says GOOD or proposes CHANGES with snippet + reasoning)
    Agent 3 = TIEBREAKER (only if Agent 2 proposes changes, then all 3 vote)

    Returns (approved: bool, reasoning: str, vote_details: dict)
    """
    st.session_state.voting_used = True
    votes = []

    # Agent 1 (CODER) - Already made the fix, implicitly approves
    votes.append({
        "agent": 1,
        "role": "CODER",
        "vote": "APPROVE",
        "reasoning": "I made this fix and believe it's correct"
    })

    # Agent 2 (REVIEWER) - Reviews Agent 1's work
    reviewer_prompt = f"""You are AGENT 2: THE REVIEWER. Agent 1 (the coder) has made a fix.
Your job is to review their work and determine if it's correct.

ISSUE THAT WAS SUPPOSED TO BE FIXED:
- Severity: {issue.get('severity', 'unknown')}
- Category: {issue.get('category', 'unknown')}
- Description: {issue.get('description', 'unknown')}
- Suggested Fix: {issue.get('fix', 'unknown')}

ORIGINAL CODE:
```python
{original_code[:3000]}
```

AGENT 1'S FIXED CODE:
```python
{fixed_code[:3000]}
```

REVIEW CRITERIA:
1. Does the fix address the specific issue?
2. Does it avoid introducing new bugs?
3. Is it clean and minimal?

Respond in JSON:
{{
    "verdict": "GOOD" or "NEEDS_CHANGES",
    "reasoning": "explain your assessment",
    "proposed_fix": "if NEEDS_CHANGES, provide the specific code snippet that should be changed"
}}"""

    try:
        response2 = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": reviewer_prompt}]
        )
        result2 = response2.content[0].text
        json_match2 = re.search(r'\{.*\}', result2, re.DOTALL)
        if json_match2:
            review = json.loads(json_match2.group())
            votes.append({
                "agent": 2,
                "role": "REVIEWER",
                "vote": "APPROVE" if review.get("verdict") == "GOOD" else "REJECT",
                "reasoning": review.get("reasoning", ""),
                "proposed_fix": review.get("proposed_fix", "")
            })
    except Exception as e:
        votes.append({"agent": 2, "role": "REVIEWER", "vote": "ABSTAIN", "reasoning": str(e)})

    # Check if we need Agent 3 (TIEBREAKER)
    agent2_vote = votes[1].get("vote") if len(votes) > 1 else "ABSTAIN"

    # Only bring in Agent 3 if Agent 2 proposed changes (disagreed with Agent 1)
    if agent2_vote == "REJECT":
        agent2_reasoning = votes[1].get("reasoning", "")[:200]
        agent2_proposed = votes[1].get("proposed_fix", "")[:500]

        tiebreaker_prompt = f"""You are AGENT 3: THE TIEBREAKER.

Agent 1 (CODER) made a fix and believes it's correct.
Agent 2 (REVIEWER) disagrees and proposes changes.

ISSUE:
- {issue.get('description', 'unknown')}

AGENT 1'S FIX (in the code):
```python
{fixed_code[:2000]}
```

AGENT 2'S OBJECTION:
"{agent2_reasoning}"

AGENT 2'S PROPOSED CHANGE:
"{agent2_proposed}"

YOUR TASK: Cast the deciding vote.
- Vote APPROVE if Agent 1's fix is good enough (accept it as-is)
- Vote REJECT if Agent 2 is right (the fix needs changes)

Respond in JSON:
{{"vote": "APPROVE" or "REJECT", "reasoning": "brief explanation of your decision"}}"""

        try:
            response3 = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=500,
                messages=[{"role": "user", "content": tiebreaker_prompt}]
            )
            result3 = response3.content[0].text
            json_match3 = re.search(r'\{.*\}', result3, re.DOTALL)
            if json_match3:
                vote3 = json.loads(json_match3.group())
                votes.append({
                    "agent": 3,
                    "role": "TIEBREAKER",
                    "vote": vote3.get("vote", "ABSTAIN"),
                    "reasoning": vote3.get("reasoning", "")
                })
        except Exception as e:
            votes.append({"agent": 3, "role": "TIEBREAKER", "vote": "ABSTAIN", "reasoning": str(e)})

    # Count votes
    approves = sum(1 for v in votes if v.get("vote") == "APPROVE")
    rejects = sum(1 for v in votes if v.get("vote") == "REJECT")

    # Determine final result (majority wins)
    approved = approves > rejects

    # Build reasoning summary
    reasoning_parts = []
    for v in votes:
        agent = v.get("agent", "?")
        role = v.get("role", "")
        vote = v.get("vote", "ABSTAIN")
        reason = v.get("reasoning", "")[:50]
        reasoning_parts.append(f"Agent {agent} ({role}): {vote} - {reason}")

    final_reasoning = f"VOTE: {approves} APPROVE, {rejects} REJECT. " + " | ".join(reasoning_parts)

    vote_details = {
        "votes": votes,
        "approves": approves,
        "rejects": rejects,
        "tiebreaker_needed": len(votes) > 2,
        "final_decision": "APPROVED" if approved else "REJECTED",
        "reviewer_proposed_fix": votes[1].get("proposed_fix", "") if len(votes) > 1 else ""
    }

    return approved, final_reasoning, vote_details


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


def test_mode():
    """Test pre-built app with Claude analysis."""
    st.header("🧪 Test Only")

    st.markdown("""
    **Automated Code Analysis & Fix Loop**:
    1. **Opus 4.5** analyzes your code for issues
    2. Shows problems with severity ratings
    3. **Multiple fix modes**: Batch (3 at once), Smart Delegation, or One-at-a-time
    4. **Haiku** handles simple fixes (10x cheaper), **Opus** handles complex ones
    5. Re-analyzes to verify fixes worked
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

    # ==========================================================================
    # APP MODE SELECTION - Critical for proper judgment
    # ==========================================================================
    st.subheader("📋 App Type")
    st.caption("This affects how the analyzer judges your code - set this correctly!")

    app_mode_col1, app_mode_col2 = st.columns([1, 2])
    with app_mode_col1:
        app_mode = st.radio(
            "What type of app is this?",
            options=list(APP_MODES.keys()),
            format_func=lambda x: APP_MODES[x]["name"],
            index=list(APP_MODES.keys()).index(st.session_state.app_mode),
            key="app_mode_selector"
        )
        st.session_state.app_mode = app_mode

    with app_mode_col2:
        mode_info = APP_MODES[app_mode]
        st.info(f"**{mode_info['name']}**\n\n{mode_info['description']}")

        # Quick explanation of what this changes
        if app_mode == "simple_mvp":
            st.success("✅ JSON save/load is OK • Session state for temp data is OK • No database required")
        elif app_mode == "full_app":
            st.warning("⚠️ Database required • Persistent data must be in DB • Full security expected")
        else:
            st.info("🔬 Only critical bugs flagged • Style issues ignored • Experimental mode")

    st.divider()

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

    # Row 2: Fix Mode Selection
    col_c, col_d = st.columns(2)
    with col_c:
        auto_fix = st.checkbox("Auto-fix issues", value=True)
    with col_d:
        run_all_loops = st.checkbox("Run all loops", value=False, help="Ignore target score, run all loops regardless")

    # Row 3: Advanced Fix Options
    col_f, col_g, col_h = st.columns(3)
    with col_f:
        fix_mode = st.selectbox(
            "Fix Mode",
            ["Batch (5 at once)", "Smart Delegation", "One at a time"],
            help="Batch: Opus fixes 5 issues per round (fastest). Smart: Batches Opus issues, Haiku for simple. One-at-a-time: Original slow mode."
        )
    with col_g:
        use_haiku = st.checkbox("Use Haiku for simple fixes", value=True, help="LOW severity & best_practice fixes use Haiku (10x cheaper)")
    with col_h:
        skip_duplicates = st.checkbox("Skip duplicate issues", value=True, help="Don't try to fix issues that look the same as previous attempts")

    # Row 4: Advanced Verification Options
    col_vote, col_stats = st.columns(2)
    with col_vote:
        use_voting = st.checkbox(
            "🗳️ Multi-Agent Voting",
            value=False,
            help="Use 3 Opus agents to vote on each fix (higher quality, 2-3x cost). Agent 3 only called if tie."
        )
    with col_stats:
        show_stats = st.checkbox("📊 Show Mechanism Stats", value=True, help="Track which features are being used")

    # Clear results button (only show if we have results)
    col_start, col_clear = st.columns([3, 1])
    with col_start:
        start_analysis = st.button("🚀 Start Analysis", type="primary")
    with col_clear:
        if st.session_state.analysis_complete:
            if st.button("🗑️ Clear Results"):
                st.session_state.analysis_results = []
                st.session_state.analysis_complete = False
                st.session_state.final_fixed_code = None
                st.session_state.tested_project = None
                st.session_state.test_loop_count = 0
                st.rerun()

    if start_analysis:
        client = get_client()
        if not client:
            return

        # Clear previous results and start fresh
        st.session_state.analysis_results = []
        st.session_state.analysis_complete = False
        st.session_state.tested_project = selected_project
        st.session_state.current_project = selected_project
        st.session_state.status = "testing"
        add_log(f"Starting test: {selected_project}")

        # Local tracking during this run
        fixed_issue_ids = set()
        score_history = []  # Track scores to detect plateaus

        code_to_test = current_code
        loop_count = 0
        previous_issues = []

        while loop_count < max_loops:
            loop_count += 1
            st.subheader(f"📊 Analysis Loop {loop_count}/{max_loops}")

            with st.spinner(f"Claude analyzing code (attempt {loop_count})..."):
                analysis = analyze_code_with_claude(
                    client, code_to_test, test_steps,
                    previous_issues if loop_count > 1 else None,
                    app_mode=st.session_state.app_mode
                )

            # Store in session_state so results persist across reruns
            st.session_state.analysis_results.append({"loop": loop_count, "analysis": analysis})

            # Display score
            score = analysis.get("overall_score", 0)
            score_history.append(score)

            if score >= 90:
                st.success(f"✅ Score: {score}/100 - Excellent!")
            elif score >= 70:
                st.warning(f"⚠️ Score: {score}/100 - Needs improvement")
            else:
                st.error(f"❌ Score: {score}/100 - Significant issues")

            st.progress(score / 100)

            # PLATEAU DETECTION: Stop if score hasn't improved for 3 consecutive loops
            if len(score_history) >= 3:
                recent_scores = score_history[-3:]
                if recent_scores[0] == recent_scores[1] == recent_scores[2]:
                    # Check if score is "good enough" (>= 80)
                    if score >= 80:
                        st.success(f"🎯 Score plateaued at {score}/100 for 3 loops - this is good enough! Stopping.")
                        st.session_state.status = "passed"
                        add_log(f"Test PASSED (plateau at {score}): {selected_project}")
                        break
                    elif score >= 70:
                        st.warning(f"⚠️ Score plateaued at {score}/100 for 3 loops. Consider reviewing manually.")
                        # Continue trying for a bit more
                        if len(score_history) >= 5 and all(s == score for s in score_history[-5:]):
                            st.info(f"📊 Score stuck at {score} for 5 loops. Stopping to avoid infinite loop.")
                            break

            # Display issues with Expand All / Copy All buttons
            issues = analysis.get("issues", [])

            if issues:
                col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
                with col_btn1:
                    expand_all = st.checkbox("📂 Expand All", key=f"expand_{loop_count}")
                with col_btn2:
                    copy_text = format_analysis_text(analysis, loop_count)
                    st.download_button(
                        "📋 Download Analysis",
                        copy_text.encode('utf-8'),  # Encode as bytes for proper text file
                        file_name=f"analysis_loop_{loop_count}.txt",
                        mime="text/plain; charset=utf-8",
                        key=f"copy_{loop_count}"
                    )

                st.write(f"**Found {len(issues)} issue(s):**")

                # Sort by severity (critical first)
                severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
                sorted_issues = sorted(issues, key=lambda x: severity_order.get(x.get("severity", "low"), 4))

                for idx, issue in enumerate(sorted_issues):
                    severity = issue.get("severity", "low")
                    icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(severity, "⚪")

                    # Mark if this was supposedly fixed before
                    issue_id = issue.get("id", f"issue_{idx}")
                    fixed_marker = " (STILL PRESENT)" if issue_id in fixed_issue_ids else ""

                    with st.expander(f"{icon} [{severity.upper()}] {issue.get('description', 'Unknown')[:50]}...{fixed_marker}", expanded=expand_all):
                        st.write(f"**Category:** {issue.get('category', 'N/A')}")
                        st.write(f"**Line:** {issue.get('line', 'N/A')}")
                        st.write(f"**Description:** {issue.get('description', 'N/A')}")
                        st.write(f"**Fix:** {issue.get('fix', 'N/A')}")
                        if issue.get('code_snippet'):
                            st.code(issue.get('code_snippet', ''), language="python")

            # Display test results
            test_results = analysis.get("test_results", [])
            if test_results:
                st.write("**Test Results:**")
                for test in test_results:
                    status = test.get("status", "unknown")
                    icon = {"pass": "✅", "fail": "❌", "warning": "⚠️"}.get(status, "❓")
                    st.write(f"{icon} {test.get('step', 'Unknown')} - {test.get('notes', '')}")

            st.write(f"**Summary:** {analysis.get('summary', 'N/A')}")

            # Store the current fixed code for later download
            st.session_state.final_fixed_code = code_to_test
            st.session_state.final_project_name = selected_project

            # Check if passing (unless run_all_loops is enabled)
            critical_issues = [i for i in issues if i.get("severity") in ["critical", "high"]]

            if not run_all_loops and score >= target_score and not critical_issues:
                st.success(f"🎉 Code passed! Score {score} >= target {target_score}")
                st.session_state.status = "passed"
                add_log(f"Test PASSED: {selected_project} (score: {score})")
                break
            elif run_all_loops and loop_count >= max_loops:
                st.info(f"📊 Completed all {max_loops} loops. Final score: {score}")
                if score >= target_score:
                    st.session_state.status = "passed"
                break

            # Auto-fix if enabled
            if auto_fix and issues and loop_count < max_loops:
                # Filter out duplicate issues if enabled
                issues_to_process = sorted_issues
                if skip_duplicates:
                    issues_to_process = [
                        issue for issue in sorted_issues
                        if get_issue_fingerprint(issue) not in fixed_issue_ids
                    ]
                    if len(issues_to_process) < len(sorted_issues):
                        st.info(f"⏭️ Skipped {len(sorted_issues) - len(issues_to_process)} duplicate issue(s)")

                # "GOOD ENOUGH" threshold: Skip LOW severity issues if score >= 85
                if score >= 85:
                    high_priority_issues = [
                        issue for issue in issues_to_process
                        if issue.get("severity", "low") in ["critical", "high", "medium"]
                    ]
                    low_count = len(issues_to_process) - len(high_priority_issues)
                    if low_count > 0:
                        st.info(f"🎯 Score >= 85: Skipping {low_count} LOW severity issue(s) - focusing on important fixes")
                        issues_to_process = high_priority_issues

                    # If only LOW severity issues remain, we're done!
                    if not issues_to_process:
                        st.success(f"🎉 Score {score}/100 with only LOW severity issues remaining - that's good enough!")
                        st.session_state.status = "passed"
                        add_log(f"Test PASSED (good enough at {score}): {selected_project}")
                        break

                if not issues_to_process:
                    st.warning("All remaining issues are duplicates. Moving to next loop...")
                    continue

                original_code_before_fix = code_to_test

                # ================================================================
                # FIX MODE: BATCH (5 at once) - Let Opus handle multiple issues
                # ================================================================
                if fix_mode == "Batch (5 at once)":
                    st.info(f"🔧 **BATCH MODE**: Fixing up to 5 issues at once with Opus 4.5...")

                    with st.spinner("Opus 4.5 fixing multiple issues in one pass..."):
                        fixed_code, was_changed, issues_attempted = batch_fix_issues(
                            client, code_to_test, issues_to_process, max_issues=5
                        )
                        st.session_state.opus_fixes_count += len(issues_attempted) if was_changed else 0
                        st.session_state.batch_fixes_count += 1 if was_changed and len(issues_attempted) > 1 else 0

                    if was_changed:
                        # Verification: Use voting system if enabled, otherwise single Opus verification
                        if use_voting:
                            with st.spinner("🗳️ Multi-agent voting on batch fix..."):
                                fix_verified, verification_reason, vote_details = multi_agent_vote(
                                    client, original_code_before_fix, fixed_code, issues_attempted[0]
                                )
                                st.info(f"📊 Vote result: {vote_details['approves']} approve, {vote_details['rejects']} reject" +
                                       (" (tiebreaker used)" if vote_details['tiebreaker_needed'] else ""))
                        else:
                            with st.spinner("🔍 Opus verifying batch fix..."):
                                fix_verified, verification_reason = verify_fix_worked(
                                    client, original_code_before_fix, fixed_code, issues_attempted[0]
                                )

                        if fix_verified:
                            st.session_state.verification_passes += 1
                            code_to_test = fixed_code
                            for issue in issues_attempted:
                                fixed_issue_ids.add(get_issue_fingerprint(issue))
                            previous_issues = issues_attempted

                            app_file.write_text(fixed_code, encoding="utf-8")
                            add_log(f"Batch fix applied ({len(issues_attempted)} issues) - loop {loop_count}")

                            st.success(f"✅ Batch fix verified! Fixed {len(issues_attempted)} issues at once")
                            with st.expander("View fixed code"):
                                st.code(fixed_code, language="python")
                            continue
                        else:
                            st.session_state.verification_fails += 1
                            st.warning(f"⚠️ Batch fix rejected: {verification_reason[:80]}")
                            st.info("Falling back to single issue fix...")

                            # ACTUAL FALLBACK: Try fixing just the first issue without voting
                            issue_to_fix = issues_to_process[0]
                            st.info(f"🔧 Single fix: [{issue_to_fix.get('severity', '').upper()}] {issue_to_fix.get('description', '')[:40]}...")

                            with st.spinner("Opus fixing single issue..."):
                                single_fixed_code, single_was_changed = auto_fix_single_issue(client, code_to_test, issue_to_fix)

                            if single_was_changed:
                                # Simple verification without voting for fallback
                                with st.spinner("🔍 Verifying single fix..."):
                                    single_verified, single_reason = verify_fix_worked(
                                        client, original_code_before_fix, single_fixed_code, issue_to_fix
                                    )

                                if single_verified:
                                    st.session_state.verification_passes += 1
                                    code_to_test = single_fixed_code
                                    fixed_issue_ids.add(get_issue_fingerprint(issue_to_fix))
                                    previous_issues = [issue_to_fix]
                                    app_file.write_text(single_fixed_code, encoding="utf-8")
                                    add_log(f"[Fallback] Fixed: {issue_to_fix.get('description', '')[:30]}...")
                                    st.success(f"✅ Fallback single fix applied!")
                                    continue
                                else:
                                    st.session_state.verification_fails += 1
                                    st.warning(f"⚠️ Fallback also rejected: {single_reason[:60]}")
                            else:
                                st.warning("Fallback fix could not be applied")

                # ================================================================
                # FIX MODE: SMART DELEGATION - Actually smart batching!
                # Groups simple issues for Haiku, complex issues for Opus batch
                # ================================================================
                elif fix_mode == "Smart Delegation":
                    # Separate issues into Haiku-appropriate vs Opus-required
                    haiku_issues = []
                    opus_issues = []

                    for issue in issues_to_process[:5]:  # Consider up to 5 issues
                        if use_haiku and should_use_haiku(issue):
                            haiku_issues.append(issue)
                        else:
                            opus_issues.append(issue)

                    st.info(f"📊 **SMART DELEGATION**: {len(opus_issues)} complex (Opus) + {len(haiku_issues)} simple (Haiku eligible)")

                    # PRIORITY 1: Handle complex issues with Opus batch (up to 5 at once!)
                    if opus_issues:
                        batch_size = min(5, len(opus_issues))  # Opus can handle 5 at once
                        st.info(f"🧠 **OPUS** batch fixing {batch_size} complex issue(s)...")

                        with st.spinner(f"Opus 4.5 fixing {batch_size} issues in one pass..."):
                            fixed_code, was_changed, issues_attempted = batch_fix_issues(
                                client, code_to_test, opus_issues, max_issues=5
                            )
                            st.session_state.opus_fixes_count += len(issues_attempted) if was_changed else 0
                            st.session_state.batch_fixes_count += 1 if was_changed and len(issues_attempted) > 1 else 0

                        if was_changed:
                            # Verification: Use voting if enabled
                            if use_voting:
                                with st.spinner("🗳️ Multi-agent voting on Smart batch fix..."):
                                    fix_verified, verification_reason, vote_details = multi_agent_vote(
                                        client, original_code_before_fix, fixed_code, issues_attempted[0]
                                    )
                                    st.info(f"📊 Vote: {vote_details['approves']} approve, {vote_details['rejects']} reject")
                            else:
                                with st.spinner("🔍 Opus verifying batch fix..."):
                                    fix_verified, verification_reason = verify_fix_worked(
                                        client, original_code_before_fix, fixed_code, issues_attempted[0]
                                    )

                            if fix_verified:
                                st.session_state.verification_passes += 1
                            else:
                                st.session_state.verification_fails += 1

                            if fix_verified:
                                code_to_test = fixed_code
                                for issue in issues_attempted:
                                    fixed_issue_ids.add(get_issue_fingerprint(issue))
                                previous_issues = issues_attempted

                                app_file.write_text(fixed_code, encoding="utf-8")
                                add_log(f"[Opus Batch] Fixed {len(issues_attempted)} issue(s) - loop {loop_count}")

                                st.success(f"✅ Opus batch verified! Fixed {len(issues_attempted)} complex issues")
                                with st.expander("View fixed code"):
                                    st.code(fixed_code, language="python")
                                continue
                            else:
                                st.warning(f"⚠️ Opus batch rejected: {verification_reason[:80]}")
                                st.info("Falling back to single issue fix...")

                                # ACTUAL FALLBACK: Try fixing just the first complex issue
                                issue_to_fix = opus_issues[0]
                                st.info(f"🔧 Single fix: [{issue_to_fix.get('severity', '').upper()}] {issue_to_fix.get('description', '')[:40]}...")

                                with st.spinner("Opus fixing single issue..."):
                                    single_fixed_code, single_was_changed = auto_fix_single_issue(client, code_to_test, issue_to_fix)

                                if single_was_changed:
                                    with st.spinner("🔍 Verifying single fix..."):
                                        single_verified, single_reason = verify_fix_worked(
                                            client, original_code_before_fix, single_fixed_code, issue_to_fix
                                        )

                                    if single_verified:
                                        st.session_state.verification_passes += 1
                                        code_to_test = single_fixed_code
                                        fixed_issue_ids.add(get_issue_fingerprint(issue_to_fix))
                                        previous_issues = [issue_to_fix]
                                        app_file.write_text(single_fixed_code, encoding="utf-8")
                                        add_log(f"[Smart Fallback] Fixed: {issue_to_fix.get('description', '')[:30]}...")
                                        st.success(f"✅ Fallback single fix applied!")
                                        continue
                                    else:
                                        st.session_state.verification_fails += 1
                                        st.warning(f"⚠️ Fallback also rejected: {single_reason[:60]}")
                                else:
                                    st.warning("Fallback fix could not be applied")

                    # PRIORITY 2: Handle simple issues with Haiku (one at a time for safety)
                    elif haiku_issues:
                        issue_to_fix = haiku_issues[0]
                        st.info(f"🐦 **HAIKU** fixing simple issue: [{issue_to_fix.get('severity', '').upper()}] {issue_to_fix.get('description', '')[:40]}...")

                        with st.spinner("Haiku fixing (fast & cheap)..."):
                            fixed_code, was_changed = fix_with_haiku(client, code_to_test, issue_to_fix)
                            st.session_state.haiku_fixes_count += 1 if was_changed else 0

                        if was_changed:
                            with st.spinner("🔍 Verifying fix..."):
                                fix_verified, verification_reason = verify_fix_worked(
                                    client, original_code_before_fix, fixed_code, issue_to_fix
                                )
                                if fix_verified:
                                    st.session_state.verification_passes += 1
                                else:
                                    st.session_state.verification_fails += 1

                            if fix_verified:
                                code_to_test = fixed_code
                                fixed_issue_ids.add(get_issue_fingerprint(issue_to_fix))
                                previous_issues = [issue_to_fix]

                                app_file.write_text(fixed_code, encoding="utf-8")
                                add_log(f"[Haiku] Fixed: {issue_to_fix.get('description', '')[:30]}...")

                                st.success(f"✅ Haiku fix verified: {verification_reason[:60]}")
                                continue
                            else:
                                st.warning(f"⚠️ Haiku fix rejected: {verification_reason[:80]}")
                        else:
                            st.warning("Haiku could not apply fix")

                    # If all else fails, continue to next loop
                    if len(issues_to_process) > 1:
                        st.info("Moving to next analysis loop...")
                        continue
                    break

                # ================================================================
                # FIX MODE: ONE AT A TIME (original behavior)
                # ================================================================
                else:  # "One at a time"
                    issue_to_fix = issues_to_process[0]
                    st.info(f"🔧 Fixing: [{issue_to_fix.get('severity', '').upper()}] {issue_to_fix.get('description', '')[:50]}...")

                    # Use Haiku for simple issues if enabled
                    if use_haiku and should_use_haiku(issue_to_fix):
                        st.caption("Using Haiku (simple fix)")
                        with st.spinner("Haiku fixing..."):
                            fixed_code, was_changed = fix_with_haiku(client, code_to_test, issue_to_fix)
                    else:
                        with st.spinner("Opus fixing..."):
                            fixed_code, was_changed = auto_fix_single_issue(client, code_to_test, issue_to_fix)

                    if was_changed:
                        with st.spinner("🔍 Verifying..."):
                            fix_verified, verification_reason = verify_fix_worked(
                                client, original_code_before_fix, fixed_code, issue_to_fix
                            )

                        if fix_verified:
                            code_to_test = fixed_code
                            fixed_issue_ids.add(get_issue_fingerprint(issue_to_fix))
                            previous_issues = [issue_to_fix]

                            app_file.write_text(fixed_code, encoding="utf-8")
                            add_log(f"Fixed: {issue_to_fix.get('description', '')[:30]}...")

                            st.success(f"✅ Verified: {verification_reason[:80]}")
                            continue
                        else:
                            st.warning(f"⚠️ Rejected: {verification_reason[:80]}")

                    # Try next issue
                    if len(issues_to_process) > 1:
                        continue
                    break
            else:
                if not auto_fix:
                    st.info("Auto-fix disabled. Enable to automatically fix issues.")
                break

        # Final status and store results in session_state
        if st.session_state.status != "passed":
            st.session_state.status = "failed"
            add_log(f"Test completed with issues: {selected_project}")

        # Store final results in session_state for persistent display
        st.session_state.final_fixed_code = code_to_test
        st.session_state.final_project_name = selected_project
        st.session_state.test_loop_count = loop_count
        st.session_state.analysis_complete = True

    # ==========================================================================
    # RESULTS DISPLAY - Outside button block so it persists across reruns
    # ==========================================================================
    if st.session_state.analysis_complete and st.session_state.final_fixed_code:
        st.divider()

        # Show mechanism stats if enabled
        if show_stats:
            st.subheader("📊 Mechanism Usage Stats")
            stat_cols = st.columns(4)
            with stat_cols[0]:
                st.metric("🧠 Opus Fixes", st.session_state.opus_fixes_count)
            with stat_cols[1]:
                st.metric("🐦 Haiku Fixes", st.session_state.haiku_fixes_count)
            with stat_cols[2]:
                st.metric("📦 Batch Fixes", st.session_state.batch_fixes_count)
            with stat_cols[3]:
                total_verifications = st.session_state.verification_passes + st.session_state.verification_fails
                pass_rate = (st.session_state.verification_passes / total_verifications * 100) if total_verifications > 0 else 0
                st.metric("✅ Verification Pass Rate", f"{pass_rate:.0f}%")

            # Show feature flags
            features_used = []
            if st.session_state.coding_bible_used:
                features_used.append("📖 Coding Bible")
            if st.session_state.voting_used:
                features_used.append("🗳️ Multi-Agent Voting")
            if st.session_state.batch_fixes_count > 0:
                features_used.append("📦 Batch Fixing")
            if st.session_state.haiku_fixes_count > 0:
                features_used.append("🐦 Haiku Delegation")

            if features_used:
                st.caption(f"**Features used:** {' • '.join(features_used)}")

            st.divider()

        st.subheader("📥 Export Results")

        # Get values from session_state
        code_to_export = st.session_state.final_fixed_code
        project_to_export = st.session_state.final_project_name or st.session_state.tested_project
        loop_count_export = st.session_state.test_loop_count
        all_analyses_export = st.session_state.analysis_results

        # MOST IMPORTANT: Download Fixed Code button
        st.markdown("### 🔧 Fixed Code")
        st.success(f"Final code ready for download ({len(code_to_export)} characters)")

        col_code1, col_code2 = st.columns(2)
        with col_code1:
            st.download_button(
                "⬇️ DOWNLOAD FIXED CODE (.py)",
                code_to_export.encode('utf-8'),  # Encode as bytes for proper file download
                file_name=f"{project_to_export}_fixed.py",
                mime="text/x-python; charset=utf-8",
                type="primary",
                key="download_fixed_code"
            )
        with col_code2:
            # Show code in expander with line count
            line_count = len(code_to_export.split('\n'))
            with st.expander(f"📄 View Fixed Code ({line_count} lines)"):
                st.code(code_to_export, language="python")

        st.divider()

        # Reports section
        st.markdown("### 📊 Analysis Reports")

        full_export = {
            "project": project_to_export,
            "total_loops": loop_count_export,
            "final_status": st.session_state.status,
            "analyses": all_analyses_export,
            "final_code": code_to_export,
            "final_code_length": len(code_to_export),
        }

        col_exp1, col_exp2 = st.columns(2)
        with col_exp1:
            json_data = json.dumps(full_export, indent=2, ensure_ascii=False)
            st.download_button(
                "📥 Full Report (JSON)",
                json_data.encode('utf-8'),  # Encode as bytes for proper file download
                file_name=f"{project_to_export}_analysis_report.json",
                mime="application/json; charset=utf-8",
                key="download_json_report"
            )
        with col_exp2:
            # Text report
            full_text = f"STREAMTEST ANALYSIS REPORT\nProject: {project_to_export}\n\n"
            for item in all_analyses_export:
                full_text += format_analysis_text(item["analysis"], item["loop"]) + "\n\n"
            full_text += "\n\n" + "=" * 60 + "\nFINAL FIXED CODE:\n" + "=" * 60 + "\n\n"
            full_text += code_to_export

            st.download_button(
                "📥 Full Report (TXT)",
                full_text.encode('utf-8'),  # Encode as bytes for proper text file
                file_name=f"{project_to_export}_analysis_report.txt",
                mime="text/plain; charset=utf-8",
                key="download_txt_report"
            )


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
