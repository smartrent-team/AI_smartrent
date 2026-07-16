import os
from dotenv import load_dotenv
from google.genai import Client

# Load environment
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("Error: GEMINI_API_KEY is not defined in .env")
    exit(1)

print(f"Testing API Key: {api_key[:15]}... ({len(api_key)} chars)")

try:
    client = Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents="Hello, Gemini! Please reply with exactly one word: 'OK'",
    )
    print("Success! Gemini response:")
    print(response.text)
except Exception as e:
    print("Error calling Gemini API:")
    print(e)
