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
# EDIT MODE - Add features to existing app
# =============================================================================

def edit_mode():
    """Edit/add features to existing app."""
    st.header("✏️ Edit / Add Features")

    st.markdown("""
    **Surgery Mode**: Only modify what's necessary. Keep everything else intact.

    1. Select or upload existing code
    2. Describe the feature to add
    3. Review planned changes BEFORE applying
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
        plan_button = st.button("📋 Plan Changes First", disabled=not feature_description)

    with col2:
        apply_button = st.button("⚡ Plan & Apply", type="primary", disabled=not feature_description)

    client = get_client()
    if not client:
        return

    if plan_button or apply_button:
        with st.spinner("Analyzing code and planning changes..."):
            plan_prompt = f"""You are an expert Python developer performing SURGICAL code edits.

CURRENT CODE:
```python
{current_code}
```

FEATURE TO ADD:
{feature_description}

RULES (STRICT):
{edit_rules}

First, analyze the code and list EXACTLY what changes need to be made.
Format your response as:

ANALYSIS:
[Brief explanation of what needs to change]

PLANNED CHANGES:
1. [File section] - [What will be added/modified]
2. [File section] - [What will be added/modified]
...

Then provide the complete updated code.

UPDATED CODE:
```python
[complete updated code here]
```
"""

            try:
                response = client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=8000,
                    messages=[{"role": "user", "content": plan_prompt}]
                )

                result = response.content[0].text

                # Extract analysis and planned changes
                if "ANALYSIS:" in result:
                    analysis = result.split("ANALYSIS:")[1].split("PLANNED CHANGES:")[0].strip()
                    st.subheader("📊 Analysis")
                    st.write(analysis)

                if "PLANNED CHANGES:" in result:
                    changes = result.split("PLANNED CHANGES:")[1].split("UPDATED CODE:")[0].strip()
                    st.subheader("📋 Planned Changes")
                    st.markdown(changes)

                # Extract new code
                new_code = ""
                if "```python" in result:
                    code_parts = result.split("```python")
                    if len(code_parts) > 1:
                        new_code = code_parts[-1].split("```")[0].strip()

                if new_code and apply_button:
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
                    })

                    st.success("✅ Changes applied!")
                    add_log(f"Applied feature: {feature_description[:50]}...")

                    with st.expander("View updated code"):
                        st.code(new_code, language="python")

                    st.session_state.current_project = project_name
                    st.session_state.status = "ready_to_test"

                elif new_code and plan_button:
                    st.subheader("🔍 Preview Updated Code")
                    st.code(new_code, language="python")
                    st.info("Click 'Plan & Apply' to save these changes")

            except Exception as e:
                st.error(f"Error: {e}")
                add_log(f"Edit error: {e}")


# =============================================================================
# TEST MODE - Test existing app
# =============================================================================

def test_mode():
    """Test pre-built app only."""
    st.header("🧪 Test Only")

    st.markdown("""
    Select a project to test. The auto-loop will:
    1. Run the app
    2. Execute test steps
    3. Fix any issues found
    4. Repeat until passing
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
        # Save uploaded file to temp project
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

    with st.expander("View code"):
        st.code(app_file.read_text(encoding="utf-8"), language="python")

    # Test configuration
    st.subheader("Test Configuration")

    test_steps = st.text_area(
        "Test steps (one per line)",
        value="Verify the page loads without errors\nCheck all buttons are clickable\nTest basic functionality",
        height=100
    )

    max_loops = st.slider("Max fix attempts", 1, 20, 10)

    if st.button("🚀 Start Testing", type="primary"):
        st.session_state.current_project = selected_project
        st.session_state.status = "testing"
        add_log(f"Starting test: {selected_project}")

        # TODO: Integrate with auto_loop.py
        st.info("Testing integration coming soon!")
        st.write("For now, run manually:")
        st.code(f"""
# Terminal 1: Start the app
cd {project_dir}
streamlit run app.py

# Terminal 2: Run tests
python auto_loop.py
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

        uploaded_state = st.file_uploader("📤 Import State", type=["json"])
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
