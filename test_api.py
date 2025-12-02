#!/usr/bin/env python3
"""Test script to verify Gemini API access via Vertex AI or AI Studio."""

import os
import sys

# Load environment variables first
from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types


def main():
    print("=" * 60)
    print("StreamTest - Gemini API Connection Test")
    print("=" * 60)
    print()

    # Check configuration
    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true"
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    api_key = os.getenv("GEMINI_API_KEY", "")

    print("--- Configuration Check ---")

    if use_vertex:
        print(f"Mode: Vertex AI")
        print(f"Project: {project or '❌ NOT SET'}")
        print(f"Location: {location}")
        print(f"Credentials: {creds_path or '(using ADC)'}")

        if not project:
            print("\n❌ ERROR: GOOGLE_CLOUD_PROJECT not set!")
            print("   Add to .env: GOOGLE_CLOUD_PROJECT=your-project-id")
            return 1

        if creds_path:
            if os.path.exists(creds_path):
                print(f"   ✅ Credentials file exists")
            else:
                print(f"   ❌ Credentials file NOT FOUND: {creds_path}")
                return 1
        else:
            print("   ⚠️  Using Application Default Credentials (ADC)")

    elif api_key:
        print(f"Mode: AI Studio API Key")
        print(f"API Key: {api_key[:8]}...{api_key[-4:]}")
    else:
        print("❌ ERROR: No authentication configured!")
        print("\nFor Vertex AI, set in .env:")
        print("  GOOGLE_GENAI_USE_VERTEXAI=true")
        print("  GOOGLE_CLOUD_PROJECT=your-project-id")
        print("  GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json")
        print("\nOr for AI Studio:")
        print("  GEMINI_API_KEY=your-api-key")
        return 1

    print()

    # Initialize client
    print("--- Initializing Client ---")
    try:
        if use_vertex:
            client = genai.Client(
                vertexai=True,
                project=project,
                location=location,
            )
            print(f"✅ Vertex AI client initialized")
        else:
            client = genai.Client(api_key=api_key)
            print(f"✅ AI Studio client initialized")
    except Exception as e:
        print(f"❌ Failed to initialize client: {e}")
        return 1

    print()

    # Test 1: Basic text generation
    print("--- Test 1: Basic Text Generation ---")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-04-17",
            contents="Say 'Hello from StreamTest!' exactly."
        )
        print(f"✅ Response: {response.text.strip()}")
    except Exception as e:
        print(f"❌ Failed: {e}")
        print("\n   This might mean:")
        print("   - API not enabled in your project")
        print("   - Service account doesn't have Vertex AI User role")
        print("   - Billing not enabled")
        return 1

    print()

    # Test 2: Computer Use capability
    print("--- Test 2: Computer Use Tool ---")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-04-17",
            contents="If you were looking at a webpage with a blue 'Submit' button, what action would you take to click it?",
            config=types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        computer_use=types.ComputerUse(
                            environment=types.Environment.ENVIRONMENT_BROWSER
                        )
                    )
                ]
            )
        )
        print(f"✅ Computer Use tool enabled!")
        print(f"   Response preview: {response.text[:150].strip()}...")
    except Exception as e:
        error_str = str(e).lower()
        if "not supported" in error_str or "permission" in error_str or "denied" in error_str:
            print(f"❌ Computer Use NOT available")
            print(f"   Error: {e}")
            print("\n   Computer Use may require:")
            print("   - Preview/allowlist access")
            print("   - Specific API enablement")
        else:
            print(f"❌ Failed: {e}")
        return 1

    print()
    print("=" * 60)
    print("✅ ALL TESTS PASSED - Ready for StreamTest!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Start your Streamlit app: streamlit run your_app.py")
    print("  2. Run StreamTest: python main.py --manual test_manuals/example_manual.md")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
