import httpx
import json

payload = {
    "model": "gemma4:e4b",
    "messages": [{"role": "user", "content": "What is the weather in Austin, TX?"}],
    "tools": [{
        "type": "function",
        "function": {
            "name": "fetch_weather",
            "description": "Fetch weather",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string"}
                },
                "required": ["location"]
            }
        }
    }]
}
try:
    response = httpx.post("http://localhost:11434/v1/chat/completions", json=payload, timeout=30)
    print(response.json())
except Exception as e:
    print(f"Error: {e}")
