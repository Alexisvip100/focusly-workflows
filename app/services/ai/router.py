import os
from google import genai

def classify_query(user_query: str) -> str:
    """
    Classifies a user query as 'simple' or 'complex'.
    Complex: needs function calling, memory access, summarizing, or project info.
    Simple: general chat, hello, thanks.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "complex"
        
    client = genai.Client(api_key=api_key)
    prompt = f"""
Analyze the user's query and classify it as either 'simple' or 'complex'.
Return ONLY the word 'simple' or 'complex'.

'complex' means the query:
- Asks to fetch or manage tasks, workspaces, or calendar.
- Asks for specific user memories, preferences, or facts.
- Requires long reasoning or summarizing.

'simple' means the query:
- Is a greeting, thank you, or general chat.
- Is very short and doesn't require tools.

User Query: {user_query}
"""
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        result = response.text.strip().lower()
        if "simple" in result:
            return "simple"
        return "complex"
    except Exception as e:
        print(f"Router error: {e}")
        return "complex" # Default to complex on failure
