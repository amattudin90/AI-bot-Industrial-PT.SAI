from google import genai
from google.genai import types
from .config import GEMINI_API_KEY, GEMINI_MODEL

SYSTEM_INSTRUCTION = """
You are Factory AI Operations Copilot for PT SAI, specializing in Industrial Engineering,
Lean Manufacturing, production capacity, machine planning, Kaizen, and operational decisions.

RULES:
1. Reply in the same language as the latest user message unless the user asks otherwise.
2. Python/Excel data supplied by the system is the SOURCE OF TRUTH for numeric facts.
3. Never invent production quantities, machine counts, cycle times, capacity, dates, or shortages.
4. If data is missing, say exactly what is missing and ask for it.
5. Distinguish clearly between FACT (from data), CALCULATION (derived from data), and RECOMMENDATION.
6. For operational analysis use:
   KESIMPULAN / ANALYSIS / RISK / RECOMMENDATION when appropriate.
7. For Kaizen requests, begin the internal result with [DOKUMEN KAIZEN] and structure:
   KONDISI SAAT INI, IDENTIFIKASI WASTE, COUNTERMEASURE, EXPECTED IMPACT, FOLLOW-UP.
8. For a calendar request, do NOT execute anything. Return:
   [JADWALKAN_KALENDER] {"summary":"...","description":"...","start_time":"YYYY-MM-DDTHH:MM:SS","end_time":"YYYY-MM-DDTHH:MM:SS"}
   Use Asia/Jakarta local time. If date/time is missing, ask for it.
9. Keep answers practical for a factory manager/IE user.
"""

class AIEngine:
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
        self.model = GEMINI_MODEL

    @property
    def active(self):
        return self.client is not None

    def build_prompt(self, user_prompt, factory_context, history=None, parameters=None):
        parameters = parameters or {}
        hist = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in (history or [])[-8:]
        )
        return f"""
FACTORY PARAMETERS:
- Gross working hours/day: {parameters.get('gross_hours','not provided')}
- Working days/month: {parameters.get('working_days','not provided')}
- Downtime %: {parameters.get('downtime','not provided')}
- Allowance %: {parameters.get('allowance','not provided')}

{factory_context}

CONVERSATION:
{hist}

LATEST USER REQUEST:
{user_prompt}
"""

    def ask(self, user_prompt, factory_context="", history=None, parameters=None, contents=None):
        if not self.active:
            raise RuntimeError("GEMINI_API_KEY belum tersedia.")
        prompt = self.build_prompt(user_prompt, factory_context, history, parameters)
        payload = [prompt] if contents is None else [*contents, prompt]
        response = self.client.models.generate_content(
            model=self.model,
            contents=payload,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION)
        )
        return response.text or "AI tidak memberikan respons."

    def ask_stream(self, user_prompt, factory_context="", history=None, parameters=None):
        if not self.active:
            raise RuntimeError("GEMINI_API_KEY belum tersedia.")
        prompt = self.build_prompt(user_prompt, factory_context, history, parameters)
        return self.client.models.generate_content_stream(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION)
        )
