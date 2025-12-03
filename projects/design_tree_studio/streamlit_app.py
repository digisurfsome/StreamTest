"""
Design Tree Studio - Main Streamlit Application

This is the entry point for the Streamlit application.
"""

import streamlit as st
import secrets
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.config.settings import settings
from app.core.db import (
    test_connection,
    initialize_schema,
    check_tables_exist,
    get_db,
)
from app.ui.layout import (
    render_header,
    render_footer,
    show_success,
    show_error,
    show_warning,
    show_info,
    render_user_selector,
    render_project_selector,
    render_create_project_form,
    render_settings_ui,
    render_project_context_ui,
    render_chat_panel,
    render_truth_doc_export_ui,
)
from app.ui.node_tree_panel import render_design_tree_panel
from app.services import (
    get_or_create_default_user,
    list_all_users,
)


def init_session_state():
    """Initialize session state variables."""
    if "show_create_project" not in st.session_state:
        st.session_state.show_create_project = False
    if "pin_verified" not in st.session_state:
        st.session_state.pin_verified = False
    if "pin_attempts" not in st.session_state:
        st.session_state.pin_attempts = 0


def check_pin_lock():
    """
    Check if PIN lock is enabled and verify PIN.

    Returns:
        bool: True if PIN is not required or verified, False otherwise
    """
    # Show success message if PIN was just verified
    if st.session_state.get('show_pin_success'):
        show_success("PIN verified! Access granted.")
        del st.session_state.show_pin_success

    # Try to get PIN from settings
    try:
        with get_db() as db:
            from app.services import get_setting
            pin_code = get_setting(db, "pin_code")

            # No PIN set, allow access
            if not pin_code or pin_code.strip() == "":
                st.session_state.pin_verified = True
                return True

            # PIN already verified in this session
            if st.session_state.get("pin_verified", False):
                return True

            # Show PIN entry form
            st.title("🔒 PIN Required")
            st.info("This application is protected with a PIN. Please enter the PIN to continue.")

            col1, col2, col3 = st.columns([1, 2, 1])

            with col2:
                pin_input = st.text_input(
                    "Enter PIN",
                    type="password",
                    key="pin_input",
                    placeholder="Enter your PIN code"
                )

                col_a, col_b = st.columns(2)

                with col_a:
                    if st.button("Unlock", type="primary", use_container_width=True):
                        if pin_input and secrets.compare_digest(str(pin_input), str(pin_code)):
                            st.session_state.pin_verified = True
                            st.session_state.pin_attempts = 0
                            st.session_state.show_pin_success = True
                            st.rerun()
                        else:
                            st.session_state.pin_attempts += 1
                            show_error(f"Incorrect PIN. Attempt {st.session_state.pin_attempts}")

                            if st.session_state.pin_attempts >= 3:
                                st.warning("Multiple failed attempts detected. Please check your PIN configuration.")

                with col_b:
                    if st.button("Exit", use_container_width=True):
                        st.stop()

            # Show hint after multiple attempts
            if st.session_state.pin_attempts >= 3:
                with st.expander("ℹ️ Need Help?"):
                    st.markdown("""
                    **To reset or change the PIN:**

                    Contact your system administrator for PIN reset assistance.
                    """)

            return False

    except Exception as e:
        # If we can't check PIN (e.g., DB not initialized), allow access
        st.session_state.pin_verified = True
        return True


def render_system_status():
    """Render the system status tab."""
    st.header("System Status")

    # Check configuration
    st.subheader("Configuration Status")
    is_valid, errors = settings.validate()

    if is_valid:
        show_success("All required configuration is present")
    else:
        show_error("Configuration incomplete")
        for error in errors:
            st.markdown(f"- {error}")
        show_warning(
            "Please create a `.env` file in the project root with the required variables. "
            "See `.env.example` for reference."
        )

    # Test database connection
    st.subheader("Database Connection")

    if not settings.DATABASE_URL:
        show_warning(
            "Database not configured. Please set DATABASE_URL in your .env file."
        )
        st.code(
            """
# Example .env file:
DATABASE_URL=postgresql://user:password@host/database
OPENAI_API_KEY=sk-...
            """,
            language="bash",
        )
    else:
        with st.spinner("Testing database connection..."):
            success, message = test_connection()

            if success:
                show_success(message)
                st.info("✅ Database is ready for use!")
            else:
                show_error(message)
                st.markdown(
                    """
                    **Troubleshooting tips:**
                    - Verify your DATABASE_URL is correct
                    - Ensure your database is running and accessible
                    - Check network connectivity
                    - For Neon, ensure your connection string includes SSL parameters
                    """
                )

    # Database Schema Status
    st.subheader("Database Schema")

    if settings.DATABASE_URL:
        try:
            tables_exist, existing_tables = check_tables_exist()

            if tables_exist and len(existing_tables) > 0:
                show_success(
                    f"Database schema is initialized ({len(existing_tables)} tables found)"
                )

                with st.expander("View existing tables"):
                    for table in sorted(existing_tables):
                        st.markdown(f"- `{table}`")
            else:
                show_warning("Database schema not initialized")
                st.markdown(
                    """
                    The database is connected but no tables have been created yet.
                    Click the button below to initialize the database schema.
                    """
                )

            # Initialize schema button
            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                if st.button(
                    "Initialize Schema",
                    type="primary",
                    disabled=tables_exist and len(existing_tables) > 0,
                ):
                    with st.spinner("Creating database tables..."):
                        success, message = initialize_schema()

                        if success:
                            show_success(message)
                            st.rerun()
                        else:
                            show_error(message)

            with col2:
                if st.button("Refresh Status"):
                    st.rerun()

        except Exception as e:
            show_error(f"Error checking schema status: {str(e)}")
    else:
        show_warning("Configure DATABASE_URL to initialize schema")

    # OpenAI configuration status
    st.subheader("OpenAI Configuration")
    if settings.OPENAI_API_KEY:
        show_success("OpenAI API key is configured")
        st.info(f"Using model: {settings.OPENAI_MODEL}")
    else:
        show_warning("OpenAI API key not configured")

    # Development info
    if settings.DEBUG:
        st.subheader("Debug Information")
        with st.expander("Show Debug Info"):
            debug_info = {
                "APP_NAME": settings.APP_NAME,
                "APP_VERSION": settings.APP_VERSION,
                "DEBUG": settings.DEBUG,
                "DATABASE_CONFIGURED": bool(settings.DATABASE_URL),
                "OPENAI_CONFIGURED": bool(settings.OPENAI_API_KEY),
                "OPENAI_MODEL": settings.OPENAI_MODEL,
            }

            if settings.DATABASE_URL:
                tables_exist, existing_tables = check_tables_exist()
                debug_info["TABLES_COUNT"] = len(existing_tables)
                debug_info["TABLES"] = existing_tables

            st.json(debug_info)

        # Model information
        with st.expander("Show Database Models"):
            st.markdown(
                """
            **Implemented Models:**
            - `UserProfile` - User accounts and profiles
            - `Project` - Design projects
            - `ProjectContext` - Project context and guidelines
            - `Node` - Hierarchical design tree nodes
            - `NodeVersion` - Version history for nodes
            - `DraftMeta` - Draft metadata and AI suggestions
            - `RantSummary` - AI-generated summaries of discussions
            - `ChatSession` - AI chat conversation sessions
            - `ChatMessage` - Individual chat messages
            - `BatonSnapshot` - Project state snapshots
            - `Settings` - Application and user settings
            """
            )


def main():
    """Main application entry point."""

    # Page configuration
    st.set_page_config(
        page_title=settings.APP_NAME,
        page_icon="🎨",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Initialize session state
    init_session_state()

    # Check PIN lock (Phase 8)
    if not check_pin_lock():
        # PIN not verified, show PIN form only
        render_footer()
        return

    # Render header
    render_header(
        settings.APP_NAME,
        "AI-Powered Design Management System",
    )

    # Check database connection first
    if not settings.DATABASE_URL:
        show_error("Database not configured. Please set DATABASE_URL in your .env file.")
        render_footer()
        return

    # Check if schema is initialized
    tables_exist, existing_tables = check_tables_exist()
    if not tables_exist or len(existing_tables) == 0:
        show_warning("Database schema not initialized. Please go to System Status tab to initialize.")
        st.info("Click 'System Status' tab below and use the 'Initialize Schema' button.")

        # Show system status tab for initialization
        tab1, tab2, tab3 = st.tabs(["System Status", "Settings", "Project Context"])

        with tab1:
            render_system_status()

        with tab2:
            st.info("Initialize database schema first to use Settings.")

        with tab3:
            st.info("Initialize database schema first to use Project Context.")

        render_footer()
        return

    # Main application with user/project selection
    with st.sidebar:
        st.header("👤 User & Project")

        # User selection with database session
        with get_db() as db:
            # Get or create default user
            default_user = get_or_create_default_user(db)
            all_users = list_all_users(db)

            # User selector
            current_user = render_user_selector(db, all_users)

            if not current_user:
                show_error("Please select a user")
                return

            st.divider()

            # Project selector
            if st.session_state.show_create_project:
                # Show create project form
                new_project = render_create_project_form(db, current_user)
                if new_project:
                    st.session_state.show_create_project = False
                    st.session_state.current_project_id = new_project.id
                    st.session_state.current_project_name = new_project.name
                    st.rerun()
            else:
                # Show project selector
                selected_project, should_create = render_project_selector(db, current_user)

                if should_create:
                    st.session_state.show_create_project = True
                    st.rerun()

                # Store selected project in session state
                if selected_project:
                    st.session_state.current_project_id = selected_project.id
                    st.session_state.current_project_name = selected_project.name

                    # Show project info
                    with st.expander("ℹ️ Project Info"):
                        st.markdown(f"**Name:** {selected_project.name}")
                        if selected_project.description:
                            st.markdown(f"**Description:** {selected_project.description}")
                        st.markdown(f"**Owner:** {current_user.username}")
                        st.markdown(f"**Created:** {selected_project.created_at.strftime('%Y-%m-%d')}")

        st.divider()
        st.caption(f"{settings.APP_NAME} v{settings.APP_VERSION}")

    # Main content area with columns (chat on left, tabs on right)
    chat_col, main_col = st.columns([1, 2])

    # Left column: Chat panel
    with chat_col:
        if st.session_state.get("current_project_id") and "current_user" in locals() and current_user:
            with get_db() as db:
                from app.services import get_project_by_id

                project = get_project_by_id(db, st.session_state.current_project_id)
                if project:
                    # Show current project banner
                    st.success(f"📁 **Current Project:** {project.name}")
                    render_chat_panel(db, current_user.id, project)
                else:
                    st.warning("⚠️ Selected project not found. Please select a project from the sidebar.")
        else:
            st.info("📁 **No Project Selected**\n\nPlease select or create a project in the left sidebar to start chatting with AI.")

    # Right column: Tabs
    with main_col:
        tab1, tab2, tab3, tab4, tab5 = st.tabs(
            ["🏠 System Status", "⚙️ Settings", "📋 Project Context", "🎨 Design Tree", "📄 Truth Doc"]
        )

        with tab1:
            render_system_status()

        with tab2:
            if "current_user" in locals() and current_user:
                with get_db() as db:
                    render_settings_ui(db, user_id=None)  # Global settings for now
            else:
                st.info("Select a user to configure settings.")

        with tab3:
            if st.session_state.get("current_project_id"):
                with get_db() as db:
                    from app.services import get_project_by_id

                    project = get_project_by_id(db, st.session_state.current_project_id)
                    if project:
                        render_project_context_ui(db, project)
                    else:
                        show_error("⚠️ Selected project not found. Please select a project from the sidebar.")
            else:
                st.info("📁 **No Project Selected**\n\nPlease select or create a project in the left sidebar to manage project context.")

        with tab4:
            if st.session_state.get("current_project_id"):
                with get_db() as db:
                    from app.services import get_project_by_id

                    project = get_project_by_id(db, st.session_state.current_project_id)
                    if project:
                        render_design_tree_panel(db, project)
                    else:
                        show_error("⚠️ Selected project not found. Please select a project from the sidebar.")
            else:
                st.info("📁 **No Project Selected**\n\nPlease select or create a project in the left sidebar to manage design tree nodes.")

        with tab5:
            if st.session_state.get("current_project_id"):
                with get_db() as db:
                    from app.services import get_project_by_id

                    project = get_project_by_id(db, st.session_state.current_project_id)
                    if project:
                        render_truth_doc_export_ui(db, project)
                    else:
                        show_error("⚠️ Selected project not found. Please select a project from the sidebar.")
            else:
                st.info("📁 **No Project Selected**\n\nPlease select or create a project in the left sidebar to export Truth Doc.")

    # Render footer
    render_footer()


if __name__ == "__main__":
    main()
