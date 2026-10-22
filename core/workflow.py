import json
import re

CALENDAR_TAG = "[JADWALKAN_KALENDER]"
KAIZEN_TAG = "[DOKUMEN KAIZEN]"

def parse_calendar_action(text):
    if CALENDAR_TAG not in text:
        return None, text
    before, after = text.split(CALENDAR_TAG, 1)
    match = re.search(r"\{.*\}", after, re.DOTALL)
    if not match:
        return None, before.strip()
    try:
        data = json.loads(match.group(0))
        required = ["summary","description","start_time","end_time"]
        if not all(data.get(k) for k in required):
            return None, before.strip()
        return data, before.strip()
    except json.JSONDecodeError:
        return None, before.strip()

def clean_kaizen(text):
    return text.replace(KAIZEN_TAG, "").strip() if KAIZEN_TAG in text else text

def split_telegram(text, max_len=4096):
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        cut = max_len
        if len(text) > max_len:
            candidate = text.rfind("\n", 0, max_len)
            if candidate > max_len * 0.6:
                cut = candidate
        chunks.append(text[:cut])
        text = text[cut:]
    return chunks
