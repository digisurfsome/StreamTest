#!/usr/bin/env python3
"""Minimal test script to verify Gemini API access."""

import os
from google import genai

# Check for API key
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("❌ ERROR: GEMINI_API_KEY environment variable not set!")
    print("\nTo fix:")
    print("  export GEMINI_API_KEY=your_api_key_here")
    exit(1)

print(f"✅ API key found: {api_key[:8]}...{api_key[-4:]}")

# Initialize client
client = genai.Client(api_key=api_key)

# Test 1: Basic text generation (should work with any API key)
print("\n--- Test 1: Basic Text Generation ---")
try:
    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-04-17",
        contents="Say 'Hello, StreamTest!' in exactly those words."
    )
    print(f"✅ Response: {response.text}")
except Exception as e:
    print(f"❌ Failed: {e}")

# Test 2: List available models
print("\n--- Test 2: Available Models ---")
try:
    models = list(client.models.list())
    computer_use_models = [m.name for m in models if "computer" in m.name.lower()]

    if computer_use_models:
        print(f"✅ Computer Use models available: {computer_use_models}")
    else:
        print("⚠️  No 'computer use' models found in list")
        print("   (This is normal - preview models may not appear in list)")

    # Show some available models
    print(f"\n   Sample models: {[m.name for m in models[:5]]}")
except Exception as e:
    print(f"❌ Failed: {e}")

# Test 3: Computer Use capability (the real test)
print("\n--- Test 3: Computer Use Tool ---")
try:
    from google.genai import types

    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-04-17",
        contents="What actions would you take to click a button labeled 'Submit'?",
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
    print(f"✅ Computer Use response received!")
    print(f"   Response: {response.text[:200]}...")
except Exception as e:
    error_str = str(e)
    if "not supported" in error_str.lower() or "permission" in error_str.lower():
        print(f"❌ Computer Use NOT enabled for your account")
        print(f"   Error: {e}")
        print("\n   You may need to:")
        print("   1. Enable the Gemini API in Google Cloud Console")
        print("   2. Request access to Computer Use preview")
        print("   3. Use Vertex AI instead of AI Studio")
    else:
        print(f"❌ Failed: {e}")

print("\n" + "="*50)
print("TEST COMPLETE")
print("="*50)
