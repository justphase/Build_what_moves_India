from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Any
from pathlib import Path
import json, random, os

app = FastAPI(title="Mera Adhikaar API")
cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type"])
SCHEMES = json.loads((Path(__file__).parent.parent / "data" / "schemes.json").read_text(encoding="utf-8"))

class Goal(BaseModel): message: str
class Profile(BaseModel): profile: dict[str, Any]
class Explain(BaseModel): profile: dict[str, Any]; scheme_id: str

def check(rule, profile):
    actual = profile.get(rule["field"])
    if actual in (None, "", "unknown"): return None
    op, value = rule["operator"], rule["value"]
    if op == "equals": return actual == value
    if op == "less_than_or_equal": return float(actual) <= float(value)
    if op == "greater_than_or_equal": return float(actual) >= float(value)
    if op == "boolean": return bool(actual) == bool(value)
    return None

def evaluate(scheme, profile):
    matched, unmatched, missing = [], [], []
    for rule in scheme["eligibility_rules"]:
        result = check(rule, profile)
        if result is True: matched.append(rule["label"])
        elif result is False: unmatched.append(rule["label"])
        else: missing.append(rule["label"])
    status = "not_match" if unmatched else ("possible_match" if missing else "likely_match")
    return {"status":status,"matched":matched,"unmatched":unmatched,"missing":missing,"documents":scheme["required_documents"]}

def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key)
    except Exception:
        return None

def fallback_understand_goal(msg: str):
    msg_lower = msg.lower()
    if any(x in msg_lower for x in ["pregnan", "maternity", "mother", "maa"]):
        return {"intent": "pregnancy_support", "possible_profile_fields": ["age", "gender", "pregnancy_status", "annual_income"]}
    if any(x in msg_lower for x in ["beti", "girl child", "daughter", "sukanya"]):
        return {"intent": "girl_child_support", "possible_profile_fields": ["child_age", "child_gender"]}
    return {"intent": "education_financial_support", "possible_profile_fields": ["age", "gender", "education_level", "year_of_study", "annual_income", "class12_percentile"]}

@app.get("/api/schemes")
def schemes(): return SCHEMES

@app.post("/api/ai/understand-goal")
def understand_goal(goal: Goal):
    client = get_openai_client()
    if client:
        try:
            model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            prompt = (
                "You are an assistant for 'Mera Adhikaar', an Indian government welfare portal helper.\n"
                "Analyze the user's intent from their message (which may be in English, Hindi, or Hinglish).\n"
                "Extract:\n"
                "- intent: a string identifier (e.g., 'pregnancy_support', 'girl_child_support', 'education_financial_support', 'disability_support', 'general_support')\n"
                "- possible_profile_fields: array of field names relevant for eligibility (e.g. ['age', 'gender', 'education_level', 'year_of_study', 'annual_income', 'class12_percentile', 'pregnancy_status'])\n\n"
                f"User message: {goal.message}"
            )
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            if content:
                parsed = json.loads(content)
                if "intent" in parsed and "possible_profile_fields" in parsed:
                    return parsed
        except Exception:
            pass
    return fallback_understand_goal(goal.message)

@app.post("/api/eligibility")
def eligibility(payload: Profile):
    rank={"likely_match":0,"possible_match":1,"not_match":2}
    items=[{"scheme":s,"result":evaluate(s,payload.profile)} for s in SCHEMES]
    return sorted(items,key=lambda x:rank[x["result"]["status"]])

@app.post("/api/ai/explain-match")
def explain(payload: Explain):
    s=next(s for s in SCHEMES if s["id"]==payload.scheme_id); result=evaluate(s,payload.profile)
    fallback_lead={"likely_match":"Your answers match the criteria we could check.","possible_match":"This may fit, but a few details still need checking.","not_match":"This does not appear to fit based on the answers provided."}[result["status"]]
    
    summary = fallback_lead
    client = get_openai_client()
    if client:
        try:
            model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            prompt = (
                f"Explain the eligibility result for scheme '{s['name']}'.\n"
                f"Evaluation result: status='{result['status']}', matched={result['matched']}, unmatched={result['unmatched']}, missing={result['missing']}.\n"
                "Provide a clear, helpful 1-2 sentence citizen-friendly explanation summary. Do NOT change or re-evaluate eligibility status."
            )
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}]
            )
            content = response.choices[0].message.content
            if content:
                summary = content.strip()
        except Exception:
            pass

    return {"summary":summary,"why_it_matters":"This informational assessment uses published criteria, not an official decision.","result":result,"next_action":s["application_steps"][0]}

@app.post("/api/applications")
def application(payload: Explain):
    return {"id":f"MA-2026-{random.randint(1000,9999)}","status":"submitted","note":"Demo application - no government application was submitted."}


# A single public deployment serves the Vite production build and the API from
# the same origin. This removes the need for a production frontend proxy/CORS setup.
DIST_DIR = Path(__file__).resolve().parents[2] / "dist"
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        target = DIST_DIR / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(DIST_DIR / "index.html")
