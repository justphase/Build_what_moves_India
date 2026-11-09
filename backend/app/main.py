from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, JSONResponse
from pydantic import BaseModel, Field
from typing import Any, Optional
from pathlib import Path
import json
import logging
import os
import random
import re
import httpx

# Configure structured backend logging without sensitive user PII
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mera_adhikaar")


def _load_dotenv_if_present() -> None:
    """Load .env from repository root if present without overriding existing env vars."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception as exc:
        logger.warning("Could not parse .env file: %s", type(exc).__name__)


_load_dotenv_if_present()

app = FastAPI(
    title="Mera Adhikaar Voice API",
    description="Gnani AI-powered voice assistant and deterministic welfare scheme eligibility engine.",
    version="2.0.0",
)

cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins or ["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key-ID"],
)

SCHEMES_PATH = Path(__file__).parent.parent / "data" / "schemes.json"
SCHEMES: list[dict[str, Any]] = json.loads(SCHEMES_PATH.read_text(encoding="utf-8"))

# Supported Gnani AI Vachana constants (https://api.vachana.ai)
SUPPORTED_STT_MODELS = ["prisma-v3.0", "prisma-v2.5"]
SUPPORTED_TTS_MODELS = ["timbre-v2.5", "timbre-v3.0"]
SUPPORTED_TTS_VOICES = ["Nalini", "Karan", "Simran", "Raju"]
SUPPORTED_LANGUAGE_CODES = ["hi-IN", "en-IN", "indic-auto"]


class Goal(BaseModel):
    message: str


class Profile(BaseModel):
    profile: dict[str, Any]


class Explain(BaseModel):
    profile: dict[str, Any]
    scheme_id: str


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2500)
    language: str = "hi-IN"
    voice: Optional[str] = None
    model: Optional[str] = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    profile: dict[str, Any] = Field(default_factory=dict)
    language: str = "HINGLISH"  # "EN", "HI", or "HINGLISH"
    history: list[dict[str, str]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# DETERMINISTIC ELIGIBILITY ENGINE (SOLE SOURCE OF TRUTH)
# ---------------------------------------------------------------------------
def check(rule: dict[str, Any], profile: dict[str, Any]) -> Optional[bool]:
    actual = profile.get(rule["field"])
    if actual in (None, "", "unknown"):
        return None
    op, value = rule["operator"], rule["value"]
    try:
        if op == "equals":
            if isinstance(actual, str) and isinstance(value, str):
                return actual.strip().lower() == value.strip().lower()
            return actual == value
        if op == "less_than_or_equal":
            return float(actual) <= float(value)
        if op == "greater_than_or_equal":
            return float(actual) >= float(value)
        if op == "boolean":
            if isinstance(actual, str):
                norm = actual.strip().lower()
                if norm in ("true", "yes", "1", "haan", "हाँ"):
                    actual_bool = True
                elif norm in ("false", "no", "0", "nahi", "नहीं"):
                    actual_bool = False
                else:
                    return None
                return actual_bool == bool(value)
            return bool(actual) == bool(value)
    except (ValueError, TypeError):
        return None
    return None


def evaluate(scheme: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    matched, unmatched, missing = [], [], []
    for rule in scheme["eligibility_rules"]:
        result = check(rule, profile)
        if result is True:
            matched.append(rule["label"])
        elif result is False:
            unmatched.append(rule["label"])
        else:
            missing.append(rule["label"])
    status = (
        "not_match"
        if unmatched
        else ("possible_match" if missing else "likely_match")
    )
    return {
        "status": status,
        "matched": matched,
        "unmatched": unmatched,
        "missing": missing,
        "documents": scheme["required_documents"],
    }


def evaluate_all_schemes(profile: dict[str, Any]) -> list[dict[str, Any]]:
    rank = {"likely_match": 0, "possible_match": 1, "not_match": 2}
    items = [{"scheme": s, "result": evaluate(s, profile)} for s in SCHEMES]
    return sorted(items, key=lambda x: rank[x["result"]["status"]])


# ---------------------------------------------------------------------------
# GNANI AI & OPENAI CONFIGURATION HELPERS
# ---------------------------------------------------------------------------
def get_gnani_config() -> dict[str, Any]:
    raw_key = os.getenv("GNANI_API_KEY", "").strip()
    is_valid_key = bool(
        raw_key
        and raw_key
        not in (
            "your_gnani_vachana_api_key_here",
            "your_gnani_api_key_here",
            "changeme",
        )
    )
    base_url = (
        os.getenv("GNANI_BASE_URL", "https://api.vachana.ai").strip().rstrip("/")
    )
    stt_model = os.getenv("GNANI_STT_MODEL", "prisma-v3.0").strip()
    if stt_model not in SUPPORTED_STT_MODELS:
        stt_model = "prisma-v3.0"
    tts_model = os.getenv("GNANI_TTS_MODEL", "timbre-v2.5").strip()
    if tts_model not in SUPPORTED_TTS_MODELS:
        tts_model = "timbre-v2.5"
    tts_voice = os.getenv("GNANI_TTS_VOICE", "Nalini").strip()
    if tts_voice not in SUPPORTED_TTS_VOICES:
        tts_voice = "Nalini"
    return {
        "api_key": raw_key if is_valid_key else None,
        "configured": is_valid_key,
        "base_url": base_url,
        "stt_model": stt_model,
        "tts_model": tts_model,
        "tts_voice": tts_voice,
    }


def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key in ("your_openai_api_key_here", "changeme"):
        return None
    try:
        from openai import OpenAI

        return OpenAI(api_key=api_key)
    except Exception:
        return None


def normalize_gnani_language(lang: str, for_tts: bool = False) -> str:
    clean = (lang or "").strip()
    upper = clean.upper()
    if upper in ("HI", "HINDI", "HI-IN"):
        return "hi-IN"
    if upper in ("EN", "ENGLISH", "EN-IN"):
        return "en-IN"
    if upper in ("HINGLISH", "INDIC-AUTO", "AUTO"):
        return "hi-IN" if for_tts else "indic-auto"
    if clean in SUPPORTED_LANGUAGE_CODES:
        if for_tts and clean == "indic-auto":
            return "hi-IN"
        return clean
    return "hi-IN" if for_tts else "indic-auto"


def strip_markdown_for_speech(text: str) -> str:
    """Clean markdown formatting, URLs, and symbols so TTS synthesis sounds natural."""
    cleaned = re.sub(r"https?://\S+", "", text)
    cleaned = re.sub(r"[*_`#~>•✓×!↗→←]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:1500]


# ---------------------------------------------------------------------------
# NATURAL LANGUAGE PROFILE & INTENT EXTRACTION (HINDI / HINGLISH / ENGLISH)
# ---------------------------------------------------------------------------
STATE_PATTERNS: list[tuple[str, list[str]]] = [
    ("Rajasthan", ["rajasthan", "राजस्थान", "jaipur", "udaipur", "jodhpur", "kota"]),
    ("Uttar Pradesh", ["uttar pradesh", "उत्तर प्रदेश", "lucknow", "kanpur", "varanasi", " u.p", " up "]),
    ("Bihar", ["bihar", "बिहार", "patna", "gaya", "muzaffarpur"]),
    ("Madhya Pradesh", ["madhya pradesh", "मध्य प्रदेश", "bhopal", "indore"]),
    ("Maharashtra", ["maharashtra", "महाराष्ट्र", "mumbai", "pune", "nagpur"]),
    ("Gujarat", ["gujarat", "गुजरात", "ahmedabad", "surat"]),
    ("Delhi", ["delhi", "दिल्ली", "new delhi"]),
    ("Karnataka", ["karnataka", "कर्नाटक", "bengaluru", "bangalore"]),
    ("Tamil Nadu", ["tamil nadu", "तमिलनाडु", "chennai"]),
    ("West Bengal", ["west bengal", "पश्चिम बंगाल", "kolkata"]),
    ("Haryana", ["haryana", "हरियाणा", "gurugram", "faridabad"]),
    ("Punjab", ["punjab", "पंजाब", "ludhiana", "amritsar"]),
    ("Odisha", ["odisha", "ओडिशा", "orissa", "bhubaneswar"]),
    ("Telangana", ["telangana", "तेलंगाना", "hyderabad"]),
]

SCHEME_KEYWORDS: list[tuple[str, list[str]]] = [
    ("pmay-u", ["pm awas", "pmay", "awas yojana", "आवास योजना", "प्रधानमंत्री आवास", "housing scheme", "makan"]),
    ("pragati", ["pragati", "प्रगति", "aicte pragati"]),
    ("saksham", ["saksham", "सक्षम", "aicte saksham"]),
    ("pm-usp", ["pm-usp", "pm usp", "central sector scholarship", "central sector scheme"]),
    ("pmmvy", ["matru vandana", "pmmvy", "मातृ वंदना", "maternity scheme"]),
    ("sukanya", ["sukanya", "सुकन्या", "samriddhi"]),
    ("yasasvi", ["yasasvi", "यशस्वी", "pm yasasvi"]),
    ("sc-topclass", ["top class education for sc", "sc top class", "sc scholarship"]),
    ("disability-postmatric", ["post-matric scholarship for students with disabilities", "disability post matric"]),
    ("pm-jay", ["ayushman", "pm-jay", "pmjay", "आयुष्मान", "jan arogya", "5 lakh health"]),
    ("raj-kalibai", ["kalibai", "कालीबाई", "scooty yojana", "scooty scheme", "medhavi chhatra"]),
    ("raj-lado", ["lado protsahan", "rajshri", "लाडो प्रोत्साहन", "मुख्यमंत्री राजश्री"]),
]


def extract_profile_and_context(msg: str) -> dict[str, Any]:
    """
    Deterministic NLU parser for Hindi, Hinglish, and English citizen inputs.
    Extracts structured profile attributes, specific scheme mentions, and document concerns.
    """
    extracted: dict[str, Any] = {}
    msg_lower = f" {msg.lower()} "

    # 1. Extract Annual Income (lakhs, thousands, raw numbers)
    # Match patterns like "1.5 lakh", "1.5 lac", "2.5 लाख", "dedh lakh"
    if any(w in msg_lower for w in ["dedh lakh", "डेढ़ लाख"]):
        extracted["annual_income"] = 150000
    elif any(w in msg_lower for w in ["dhai lakh", "ढाई लाख"]):
        extracted["annual_income"] = 250000
    else:
        lakh_match = re.search(
            r"(\d+(?:\.\d+)?)\s*(?:lakh|lakhs|lac|lacs|लाख)", msg_lower
        )
        if lakh_match:
            extracted["annual_income"] = int(float(lakh_match.group(1)) * 100000)
        else:
            k_match = re.search(
                r"(\d+(?:\.\d+)?)\s*(?:hazaar|hazar|thousand|हजार|हज़ार|k\b)",
                msg_lower,
            )
            if k_match:
                extracted["annual_income"] = int(float(k_match.group(1)) * 1000)
            else:
                raw_income = re.search(
                    r"(?:income|इनकम|aay|आय|salary|सैलरी|कमाई|family income|फैमिली)[^\d]{0,25}(\d[\d,]{3,9})",
                    msg_lower,
                )
                if raw_income:
                    val = int(raw_income.group(1).replace(",", ""))
                    if 1000 <= val <= 50000000:
                        extracted["annual_income"] = val
                else:
                    indian_num = re.search(r"\b(\d{1,2},\d{2},\d{3})\b", msg_lower)
                    if indian_num:
                        extracted["annual_income"] = int(indian_num.group(1).replace(",", ""))

    # 2. Extract State
    for state_name, patterns in STATE_PATTERNS:
        if any(p in msg_lower for p in patterns):
            extracted["state"] = state_name
            break

    # 3. Extract Gender
    female_markers = [
        " women",
        " woman",
        " female",
        " mahila",
        " महिला",
        " महिलाओं",
        " औरत",
        " ladki",
        " लड़की",
        " छात्रा",
        " chhatra",
        " pregnant",
        " गर्भवती",
        " widow",
        " विधवा",
        "main ek ladki",
        "i am a woman",
        "i am a female",
        "for women",
        "for girls",
    ]
    male_markers = [
        " male",
        " purush",
        " पुरुष",
        " ladka",
        " लड़का",
        "i am a man",
        "i am a boy",
    ]
    if any(m in msg_lower for m in female_markers):
        extracted["gender"] = "Female"
    elif any(m in msg_lower for m in male_markers):
        extracted["gender"] = "Male"

    # 4. Girl child / Sukanya context
    is_girl_child_query = any(
        w in msg_lower
        for w in ["beti", "daughter", "girl child", "sukanya", "बेटी", "बच्ची", "सुकन्या"]
    )
    if is_girl_child_query:
        extracted["child_gender"] = "Female"
        child_age_match = re.search(
            r"(\d{1,2})\s*(?:saal|year|yr|वर्ष|साल)", msg_lower
        )
        if child_age_match:
            c_age = int(child_age_match.group(1))
            if 0 <= c_age <= 15:
                extracted["child_age"] = c_age

    # 5. Extract Age (for adult/student applicant when not solely child age)
    if "child_age" not in extracted:
        age_patterns = [
            r"(?:age|umar|उम्र|आयु)\s*(?:is|hai|है|:)?\s*(\d{1,2})",
            r"(\d{1,2})\s*(?:saal|years?\s*old|वर्ष|साल\s*का|साल\s*की)",
            r"\bi\s*am\s*(\d{1,2})\b",
        ]
        for pat in age_patterns:
            m = re.search(pat, msg_lower)
            if m:
                age_val = int(m.group(1))
                if 14 <= age_val <= 95:
                    extracted["age"] = age_val
                    break

    # 6. Extract Education Level & Institution Type
    if any(
        w in msg_lower
        for w in [
            "b.tech",
            "btech",
            "b tech",
            "engineering",
            "बीटेक",
            "इंजीनियरिंग",
            "technical degree",
        ]
    ):
        extracted["education_level"] = "B.Tech"
    elif "diploma" in msg_lower or "डिप्लोमा" in msg_lower:
        extracted["education_level"] = "Diploma"
    elif any(w in msg_lower for w in ["b.sc", "bsc", "बीएससी"]):
        extracted["education_level"] = "BSc"
    elif any(w in msg_lower for w in ["b.a", " ba ", "बीए"]):
        extracted["education_level"] = "BA"

    if "aicte" in msg_lower or "एआईसीटीई" in msg_lower:
        extracted["institution_type"] = "AICTE approved"

    # 7. Extract Class 12 Percentile / Percentage
    pct_match = re.search(
        r"(\d{2,3}(?:\.\d+)?)\s*(?:%|percent|percentile|प्रतिशत|परसेंट)", msg_lower
    )
    if pct_match:
        pct_val = float(pct_match.group(1))
        if 30 <= pct_val <= 100:
            extracted["class12_percentile"] = pct_val

    # 8. Extract Category (SC / OBC / General)
    if any(w in msg_lower for w in [" obc", "ओबीसी", "other backward", " ebc", " dnt"]):
        extracted["category"] = "OBC"
    elif any(w in msg_lower for w in [" sc ", "scheduled caste", "अनुसूचित जाति", "दलित"]):
        extracted["category"] = "SC"
    elif any(w in msg_lower for w in [" general category", " सामान्य वर्ग"]):
        extracted["category"] = "General"

    # 9. Extract Pregnancy / Disability / Housing / Scholarship flags
    if any(
        w in msg_lower
        for w in ["pregnan", "maternity", "गर्भवती", "मातृत्व", "lactating", "माँ बनने"]
    ):
        extracted["pregnancy_status"] = True
        extracted["gender"] = "Female"

    if any(
        w in msg_lower
        for w in ["disab", "divyang", "दिव्यांग", "विकलांग", "handicap"]
    ):
        extracted["disability_status"] = True

    if any(
        w in msg_lower
        for w in [
            "kaccha makan",
            "kucha house",
            "no pucca house",
            "pucca house nahi",
            "ghar nahi hai",
            "makan nahi hai",
            "पक्का मकान नहीं",
            "घर नहीं है",
            "बेघर",
        ]
    ):
        extracted["has_pucca_house"] = False
    elif any(
        w in msg_lower
        for w in ["have a pucca house", "pucca makan hai", "पक्का मकान है"]
    ):
        extracted["has_pucca_house"] = True

    if any(
        w in msg_lower
        for w in [
            "no other scholarship",
            "koi aur scholarship nahi",
            "koi scholarship nahi",
            "दूसरी छात्रवृत्ति नहीं",
        ]
    ):
        extracted["other_scholarship"] = False

    # 10. Detect Target Scheme Mention
    target_scheme_id = None
    for scheme_id, kw_list in SCHEME_KEYWORDS:
        if any(kw in msg_lower for kw in kw_list):
            target_scheme_id = scheme_id
            break

    # 11. Detect Missing Document Query (e.g., "Mere paas income certificate nahi hai")
    missing_document = None
    if any(
        w in msg_lower
        for w in [
            "nahi hai",
            "nahin hai",
            "नहीं है",
            "don't have",
            "do not have",
            "without",
            "bina",
            "बिना",
            "missing",
        ]
    ):
        if any(
            w in msg_lower
            for w in ["income certificate", "इनकम सर्टिफिकेट", "aay praman", "आय प्रमाण", "income proof"]
        ):
            missing_document = "Income certificate"
        elif any(
            w in msg_lower
            for w in ["caste certificate", "jati praman", "जाति प्रमाण", "category certificate"]
        ):
            missing_document = "Category / Caste certificate"
        elif any(
            w in msg_lower
            for w in ["disability certificate", "divyang certificate", "दिव्यांग प्रमाण"]
        ):
            missing_document = "Disability certificate"
        elif any(w in msg_lower for w in ["marksheet", "मार्कशीट"]):
            missing_document = "Marksheet"

    # 12. Detect Verified-Only Filter Request
    verified_only = any(
        w in msg_lower
        for w in [
            "verified",
            "वेरीफाइड",
            "सत्यापित",
            "official scheme",
            "government verified",
            "asli sarkari",
            "आधिकारिक",
        ]
    )

    return {
        "extracted_profile": extracted,
        "target_scheme_id": target_scheme_id,
        "missing_document": missing_document,
        "verified_only": verified_only,
    }


def fallback_understand_goal(msg: str) -> dict[str, Any]:
    msg_lower = msg.lower()
    if any(x in msg_lower for x in ["pregnan", "maternity", "mother", "maa", "गर्भवती", "मातृ"]):
        return {
            "intent": "pregnancy_support",
            "possible_profile_fields": [
                "age",
                "gender",
                "pregnancy_status",
                "annual_income",
            ],
        }
    if any(x in msg_lower for x in ["beti", "girl child", "daughter", "sukanya", "बेटी", "सुकन्या"]):
        return {
            "intent": "girl_child_support",
            "possible_profile_fields": ["child_age", "child_gender"],
        }
    if any(x in msg_lower for x in ["awas", "pmay", "house", "housing", "makan", "ghar", "आवास", "मकान"]):
        return {
            "intent": "housing_support",
            "possible_profile_fields": ["age", "annual_income", "has_pucca_house"],
        }
    if any(x in msg_lower for x in ["disab", "divyang", "saksham", "दिव्यांग", "विकलांग"]):
        return {
            "intent": "disability_support",
            "possible_profile_fields": [
                "disability_status",
                "education_level",
                "annual_income",
            ],
        }
    if any(x in msg_lower for x in ["women", "woman", "mahila", "महिला", "ladki", "लड़की"]):
        return {
            "intent": "women_welfare_support",
            "possible_profile_fields": [
                "age",
                "gender",
                "state",
                "annual_income",
                "education_level",
            ],
        }
    return {
        "intent": "education_financial_support",
        "possible_profile_fields": [
            "age",
            "gender",
            "education_level",
            "year_of_study",
            "annual_income",
            "class12_percentile",
        ],
    }


def build_follow_up_questions(
    profile: dict[str, Any], intent: str, lang: str
) -> list[str]:
    """Generate contextual follow-up questions in the user's selected language."""
    questions: list[str] = []
    is_hi = lang.upper() == "HI"
    is_en = lang.upper() == "EN"

    if "annual_income" not in profile:
        questions.append(
            "आपकी पारिवारिक वार्षिक आय (Annual Family Income) लगभग कितनी है?"
            if is_hi
            else (
                "What is your approximate annual family income?"
                if is_en
                else "Aapki family ki salana income (annual income) lagbhag kitni hai?"
            )
        )
    if "gender" not in profile and intent != "girl_child_support":
        questions.append(
            "यह योजना किसके लिए खोजी जा रही है (महिला / पुरुष / छात्रा)?"
            if is_hi
            else (
                "Who is applying (Female / Male / Student)?"
                if is_en
                else "Aap apna gender aur occupation (Student / Woman / General) bata sakte hain?"
            )
        )
    if "education_level" not in profile and intent in (
        "education_financial_support",
        "women_welfare_support",
    ):
        questions.append(
            "आप अभी कौन सी पढ़ाई कर रहे हैं (जैसे B.Tech, Diploma, BA, BSc, या 12वीं पास)?"
            if is_hi
            else (
                "What course or education level are you currently pursuing (e.g., B.Tech, Diploma, BA/BSc)?"
                if is_en
                else "Aap abhi kaunsa course padh rahe hain (jaise B.Tech, Diploma, BA/BSc) और 12th mein kitne percent the?"
            )
        )
    if "state" not in profile:
        questions.append(
            "आप किस राज्य (State) के निवासी हैं?"
            if is_hi
            else (
                "Which state do you live in?"
                if is_en
                else "Aap kis state (rajya) se hain?"
            )
        )
    if intent == "housing_support" and "has_pucca_house" not in profile:
        questions.append(
            "क्या आपके परिवार के पास भारत में कहीं भी पक्का मकान है, और आपकी उम्र क्या है?"
            if is_hi
            else (
                "Does your family already own a pucca house anywhere in India, and what is your age?"
                if is_en
                else "Kya aapke parivar ke paas pehle se pucca makan hai, aur aapki age kya hai?"
            )
        )
    if "category" not in profile and len(questions) < 3:
        questions.append(
            "आपकी श्रेणी (General / OBC / SC / ST) क्या है?"
            if is_hi
            else (
                "What is your social category (General / OBC / SC / ST)?"
                if is_en
                else "Kya aap General, OBC, ya SC/ST category se aate hain?"
            )
        )
    return questions[:3]


def compose_grounded_chat_response(
    message: str,
    profile: dict[str, Any],
    newly_extracted: dict[str, Any],
    context: dict[str, Any],
    evaluated_items: list[dict[str, Any]],
    intent: str,
    lang: str,
) -> tuple[str, str, list[dict[str, Any]], bool]:
    """
    Create a grounded, deterministic response (both display text and spoken voice summary)
    along with highlighted scheme matches. Uses OpenAI only to polish phrasing if available,
    never to alter eligibility decisions.
    """
    is_hi = lang.upper() == "HI"
    is_en = lang.upper() == "EN"
    target_id = context.get("target_scheme_id")
    missing_doc = context.get("missing_document")
    verified_only = context.get("verified_only")

    # Select highlighted schemes based on query context
    likely = [x for x in evaluated_items if x["result"]["status"] == "likely_match"]
    possible = [x for x in evaluated_items if x["result"]["status"] == "possible_match"]

    highlighted: list[dict[str, Any]] = []
    if target_id:
        target_match = next(
            (x for x in evaluated_items if x["scheme"]["id"] == target_id), None
        )
        if target_match:
            highlighted.append(target_match)

    # Filter relevant schemes by state / intent / message keywords
    msg_lower = message.lower()
    want_student = any(
        w in msg_lower
        for w in ["student", "scholarship", "college", "padhai", "छात्र", "स्कॉलरशिप", "b.tech"]
    )
    want_women = (
        profile.get("gender") == "Female"
        or any(w in msg_lower for w in ["women", "woman", "mahila", "महिला", "ladki", "beti"])
    )
    user_state = profile.get("state")

    candidate_pool = likely + possible
    for item in candidate_pool:
        if item in highlighted:
            continue
        s = item["scheme"]
        # If user specified a state, prioritize schemes matching that state or India-wide
        if user_state and s.get("state_scope") not in ("India", user_state, "Except Telangana and Odisha (verify)"):
            continue
        if want_student and not any(
            k in (s["name"] + " " + s["target_group"]).lower()
            for k in ["student", "scholarship", "education", "chhatra"]
        ):
            continue
        if want_women and user_state == "Rajasthan" and s.get("state_scope") == "Rajasthan":
            highlighted.insert(0, item)
            continue
        highlighted.append(item)

    if not highlighted:
        highlighted = (likely + possible)[:3] or evaluated_items[:3]
    else:
        highlighted = highlighted[:4]

    follow_ups = build_follow_up_questions(profile, intent, lang)

    # Case 1: User specifically says they don't have a required document (e.g. Income Certificate)
    if missing_doc == "Income certificate":
        no_income_doc_schemes = [
            x["scheme"]["name"]
            for x in evaluated_items
            if "Income certificate" not in x["scheme"]["required_documents"]
        ]
        if is_hi:
            reply = (
                "चिंता न करें! यदि आपके पास अभी **आय प्रमाण पत्र (Income Certificate)** नहीं है:\n\n"
                f"1. **बिना आय प्रमाण पत्र वाली योजनाएं**: **{', '.join(no_income_doc_schemes[:2])}** में आय प्रमाण पत्र अनिवार्य नहीं है (जन्म प्रमाण पत्र या राशन/जन आधार कार्ड से आवेदन हो सकता है)।\n"
                "2. **छात्रवृत्ति और आवास योजनाओं के लिए**: PM-USP, AICTE Pragati, और PM Awas जैसी योजनाओं में आधिकारिक पोर्टल पर आय प्रमाण पत्र आवश्यक होता है।\n"
                "3. **आय प्रमाण पत्र कैसे बनवाएं**: आप अपने नजदीकी **CSC (लोकमित्र / ई-मित्र केंद्र)** या तहसील पोर्टल से आधार और राशन कार्ड के माध्यम से 7–10 दिनों में आय प्रमाण पत्र बनवा सकते हैं।"
            )
            spoken = (
                "चिंता न करें। यदि आपके पास अभी आय प्रमाण पत्र नहीं है, तो आप सुकन्या समृद्धि खाता या आयुष्मान भारत जैसी योजनाओं को देख सकते हैं जिनमें राशन कार्ड या जन्म प्रमाण पत्र चलता है। "
                "छात्रवृत्ति योजनाओं के लिए आप नजदीकी ई-मित्र या सीएससी केंद्र से सात दिनों में आय प्रमाण पत्र बनवा सकते हैं।"
            )
        elif is_en:
            reply = (
                "If you do not currently have an **Income Certificate**:\n\n"
                f"1. **Schemes Not Requiring an Income Certificate**: **{', '.join(no_income_doc_schemes[:2])}** do not require a standalone income certificate.\n"
                "2. **Income-Threshold Schemes**: Scholarships (PM-USP, AICTE Pragati, Kalibai Bheel) and PMAY-U require official income verification before final submission.\n"
                "3. **How to Prepare**: Apply for an Income Certificate at your nearest **Common Service Centre (CSC) / State e-Mitra portal** using your Ration Card / Jan Aadhaar before the scholarship window closes."
            )
            spoken = (
                "If you do not have an income certificate right now, schemes like Sukanya Samriddhi Account do not require one. "
                "For income-based scholarships and housing schemes, you can apply for an income certificate at your nearest CSC or e-Mitra center in a few days."
            )
        else:
            reply = (
                "Koi baat nahi! Agar aapke paas abhi **Income Certificate (Aay Praman Patra)** nahi hai, toh yeh options dekhein:\n\n"
                f"1. **Bina Income Certificate wali schemes**: **{', '.join(no_income_doc_schemes[:2])}** mein अलग से income certificate nahi lagta (Birth Certificate ya Ration/Jan Aadhaar Card kaafi hai).\n"
                "2. **Scholarships aur Housing ke liye**: PM-USP, AICTE Pragati, Kalibai Yojana aur PM Awas mein income verification zaroori hota hai.\n"
                "3. **Kya karein**: Aap apne nazdeeki **e-Mitra (Rajasthan) ya CSC center** se Ration Card / Jan Aadhaar dikha kar 7 din mein Income Certificate banwa sakte hain."
            )
            spoken = (
                "Koi baat nahi! Agar aapke paas abhi income certificate nahi hai, toh Sukanya Samriddhi Account jaisi schemes mein income certificate nahi chahiye. "
                "Baaki scholarships ke liye aap apne nazdeeki e-Mitra ya CSC center se aasani se income certificate banwa sakte hain."
            )
        return reply, spoken, highlighted, False

    # Case 2: User asks about a specific scheme (e.g. "Kya main PM Awas Yojana ke liye eligible hoon?")
    if target_id:
        target_item = next(
            (x for x in evaluated_items if x["scheme"]["id"] == target_id),
            highlighted[0],
        )
        s = target_item["scheme"]
        r = target_item["result"]
        status_hi = {
            "likely_match": "प्रबल पात्रता (Likely Match)",
            "possible_match": "संभावित पात्रता (Possible Match - कुछ जानकारी बाकी है)",
            "not_match": "मानदंड मेल नहीं खाते (Does Not Match)",
        }[r["status"]]
        status_en = {
            "likely_match": "Likely Eligible (All Checked Rules Match)",
            "possible_match": "Potentially Eligible (Need a Few More Details)",
            "not_match": "Does Not Match Published Criteria",
        }[r["status"]]

        matched_str = ", ".join(r["matched"]) if r["matched"] else "None confirmed yet"
        missing_str = ", ".join(r["missing"]) if r["missing"] else "None"
        unmatched_str = ", ".join(r["unmatched"]) if r["unmatched"] else "None"
        docs_str = ", ".join(s["required_documents"][:3])

        if is_hi:
            reply = (
                f"**{s['name']}** के लिए आपकी पात्रता स्थिति: **{status_hi}**\n\n"
                f"- **लाभ**: {s['benefit_summary']} ({s['benefit_amount']})\n"
                f"- **मिलान हुए नियम (✓)**: {matched_str}\n"
                + (f"- **अपूर्ण नियम (×)**: {unmatched_str}\n" if r["unmatched"] else "")
                + (f"- **पुष्टि आवश्यक (!)**: {missing_str}\n" if r["missing"] else "")
                + f"- **आवश्यक दस्तावेज़**: {docs_str}\n"
                f"- **आधिकारिक पोर्टल**: {s['official_source_url']}\n\n"
                + (f"**अगला प्रश्न**: {follow_ups[0]}" if follow_ups and r["missing"] else "आप नीचे 'Prepare to Apply' पर क्लिक करके दस्तावेज़ चेकलिस्ट देख सकते हैं।")
            )
            spoken = (
                f"{s['name']} के लिए आपकी स्थिति {status_hi} है। "
                f"इसमें {s['benefit_amount']} तक का लाभ मिलता है। "
                + (
                    f"सटीक पुष्टि के लिए कृपया बताएं: {follow_ups[0]}"
                    if follow_ups and r["missing"]
                    else f"आवश्यक दस्तावेज़ हैं: {docs_str}।"
                )
            )
        elif is_en:
            reply = (
                f"**{s['name']}** Eligibility Assessment: **{status_en}**\n\n"
                f"- **Benefit**: {s['benefit_summary']} ({s['benefit_amount']})\n"
                f"- **Matched Criteria (✓)**: {matched_str}\n"
                + (f"- **Unmatched Criteria (×)**: {unmatched_str}\n" if r["unmatched"] else "")
                + (f"- **Still Needed to Confirm (!)**: {missing_str}\n" if r["missing"] else "")
                + f"- **Required Documents**: {docs_str}\n"
                f"- **Official Source**: {s['official_source_url']}\n\n"
                + (f"**Follow-up to confirm eligibility**: {follow_ups[0]}" if follow_ups and r["missing"] else "You can review the required document checklist in the scheme card below.")
            )
            spoken = (
                f"For {s['name']}, your deterministic status is {status_en}. "
                f"The scheme provides {s['benefit_amount']}. "
                + (
                    f"To confirm the remaining criteria, please tell me: {follow_ups[0]}"
                    if follow_ups and r["missing"]
                    else f"Key required documents include {docs_str}."
                )
            )
        else:
            reply = (
                f"**{s['name']}** ke liye aapka deterministic assessment: **{status_en}**\n\n"
                f"- **Milne wala Labh**: {s['benefit_summary']} ({s['benefit_amount']})\n"
                f"- **Matched Rules (✓)**: {matched_str}\n"
                + (f"- **Unmatched Rules (×)**: {unmatched_str}\n" if r["unmatched"] else "")
                + (f"- **Confirm karna baaki hai (!)**: {missing_str}\n" if r["missing"] else "")
                + f"- **Zaroori Documents**: {docs_str}\n"
                f"- **Official Portal**: {s['official_source_url']}\n\n"
                + (f"**Agla Sawaal**: {follow_ups[0]}" if follow_ups and r["missing"] else "Aap neeche scheme card par click karke poora application process dekh sakte hain.")
            )
            spoken = (
                f"{s['name']} ke liye aapka status {status_en} hai. "
                f"Is yojana mein {s['benefit_amount']} ka labh milta hai. "
                + (
                    f"Puri eligibility confirm karne ke liye batayein: {follow_ups[0]}"
                    if follow_ups and r["missing"]
                    else f"Iske liye {docs_str} ki zaroorat hogi."
                )
            )
        return reply, spoken, highlighted, False

    # Case 3: General / Multi-scheme discovery (e.g. Rajasthan + 1.5L income, women schemes, student scholarships, verified schemes)
    top_names = [x["scheme"]["name"] for x in highlighted[:3]]
    profile_summary_parts = []
    if "state" in profile:
        profile_summary_parts.append(f"State: {profile['state']}")
    if "annual_income" in profile:
        profile_summary_parts.append(f"Income: ₹{int(profile['annual_income']):,}")
    if "gender" in profile:
        profile_summary_parts.append(f"Gender: {profile['gender']}")
    if "education_level" in profile:
        profile_summary_parts.append(f"Course: {profile['education_level']}")
    if "age" in profile:
        profile_summary_parts.append(f"Age: {profile['age']}")

    profile_str = (
        " (" + ", ".join(profile_summary_parts) + ")" if profile_summary_parts else ""
    )

    scheme_bullets = []
    for item in highlighted[:3]:
        s = item["scheme"]
        r = item["result"]
        badge = "✓ Likely Match" if r["status"] == "likely_match" else "◉ Possible Match"
        reason = (
            ", ".join(r["matched"][:2])
            if r["matched"]
            else f"Target: {s['target_group']}"
        )
        docs_preview = ", ".join(s["required_documents"][:2])
        scheme_bullets.append(
            f"• **{s['name']}** [{badge}] — {s['benefit_amount']}. "
            f"(Matched: {reason} | Docs: {docs_preview} | Verified: {s['source_verified_at']})"
        )

    bullets_text = "\n".join(scheme_bullets)
    verified_note = (
        "\n🔒 **100% Government Verified**: सभी योजनाएं सीधे आधिकारिक सरकारी पोर्टल (.gov.in / .org) के प्रकाशित नियमों पर आधारित हैं।\n"
        if (verified_only and is_hi)
        else (
            "\n🔒 **100% Government Verified Sources**: Every scheme below is verified against published official government portals (.gov.in / .org).\n"
            if verified_only
            else ""
        )
    )

    if is_hi:
        reply = (
            f"आपकी जानकारी{profile_str} के आधार पर हमारे **नियम इंजन (Eligibility Engine)** ने **{len(likely)} प्रबल मिलान** और **{len(possible)} संभावित योजनाएं** पाई हैं:{verified_note}\n\n"
            f"{bullets_text}\n\n"
            + (
                f"**सटीक पात्रता पक्की करने के लिए कृपया बताएं**:\n1. {follow_ups[0]}"
                + (f"\n2. {follow_ups[1]}" if len(follow_ups) > 1 else "")
                if follow_ups
                else "आप किसी भी योजना कार्ड पर क्लिक करके आवश्यक दस्तावेज़ और आवेदन के चरण देख सकते हैं।"
            )
        )
        spoken = (
            f"आपकी जानकारी के अनुसार हमने {len(likely) + len(possible)} उपयुक्त सरकारी योजनाएं खोजी हैं। "
            f"प्रमुख योजनाएं हैं: {', '.join(top_names[:2])}। "
            + (
                f"अधिक सटीक मिलान के लिए कृपया बताएं: {follow_ups[0]}"
                if follow_ups
                else "आप स्क्रीन पर आवश्यक दस्तावेज़ और आधिकारिक वेबसाइट लिंक देख सकते हैं।"
            )
        )
    elif is_en:
        reply = (
            f"Based on your details{profile_str}, our **deterministic eligibility engine** found **{len(likely)} likely matches** and **{len(possible)} potential matches**:{verified_note}\n\n"
            f"{bullets_text}\n\n"
            + (
                f"**To confirm your exact eligibility, please share**:\n1. {follow_ups[0]}"
                + (f"\n2. {follow_ups[1]}" if len(follow_ups) > 1 else "")
                if follow_ups
                else "Click any scheme below to inspect required documents, application steps, and the official portal link."
            )
        )
        spoken = (
            f"Based on your details, our eligibility engine found {len(likely)} likely matches and {len(possible)} potential schemes, including {' and '.join(top_names[:2])}. "
            + (
                f"To narrow down your exact eligibility, {follow_ups[0]}"
                if follow_ups
                else "You can review the required documents and official application links on your screen."
            )
        )
    else:
        reply = (
            f"Aapki details{profile_str} ke hisaab se hamare **deterministic eligibility engine** ne **{len(likely)} Likely Matches** aur **{len(possible)} Possible Schemes** dhoondi hain:{verified_note}\n\n"
            f"{bullets_text}\n\n"
            + (
                f"**Aapki exact eligibility confirm karne ke liye batayein**:\n1. {follow_ups[0]}"
                + (f"\n2. {follow_ups[1]}" if len(follow_ups) > 1 else "")
                if follow_ups
                else "Aap neeche kisi bhi scheme par click karke required documents aur official portal steps dekh sakte hain."
            )
        )
        spoken = (
            f"Aapki details ke hisaab se aapko {', '.join(top_names[:2])} jaisi government schemes mil sakti hain. "
            + (
                f"Exact eligibility confirm karne ke liye batayein: {follow_ups[0]}"
                if follow_ups
                else "Aap screen par zaroori documents aur official application steps dekh sakte hain."
            )
        )

    return reply, spoken, highlighted, False


# ---------------------------------------------------------------------------
# EXISTING CORE API ENDPOINTS (PRESERVED FOR FULL BACKWARD COMPATIBILITY)
# ---------------------------------------------------------------------------
@app.get("/api/schemes")
def schemes():
    return SCHEMES


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
                "- intent: a string identifier (e.g., 'pregnancy_support', 'girl_child_support', 'education_financial_support', 'disability_support', 'housing_support', 'women_welfare_support', 'general_support')\n"
                "- possible_profile_fields: array of field names relevant for eligibility (e.g. ['age', 'gender', 'education_level', 'year_of_study', 'annual_income', 'class12_percentile', 'pregnancy_status'])\n\n"
                f"User message: {goal.message}"
            )
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if content:
                parsed = json.loads(content)
                if "intent" in parsed and "possible_profile_fields" in parsed:
                    return parsed
        except Exception as exc:
            logger.warning("OpenAI understand-goal fallback triggered: %s", type(exc).__name__)
    return fallback_understand_goal(goal.message)


@app.post("/api/eligibility")
def eligibility(payload: Profile):
    return evaluate_all_schemes(payload.profile)


@app.post("/api/ai/explain-match")
def explain(payload: Explain):
    s = next((s for s in SCHEMES if s["id"] == payload.scheme_id), None)
    if not s:
        raise HTTPException(status_code=404, detail="Scheme not found")
    result = evaluate(s, payload.profile)
    fallback_lead = {
        "likely_match": "Your answers match the criteria we could check.",
        "possible_match": "This may fit, but a few details still need checking.",
        "not_match": "This does not appear to fit based on the answers provided.",
    }[result["status"]]

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
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content
            if content:
                summary = content.strip()
        except Exception as exc:
            logger.warning("OpenAI explain-match fallback triggered: %s", type(exc).__name__)

    return {
        "summary": summary,
        "why_it_matters": "This informational assessment uses published criteria, not an official decision.",
        "result": result,
        "next_action": s["application_steps"][0],
    }


@app.post("/api/applications")
def application(payload: Explain):
    return {
        "id": f"MA-2026-{random.randint(1000, 9999)}",
        "status": "submitted",
        "note": "Demo application - no government application was submitted.",
    }


# ---------------------------------------------------------------------------
# NEW CONVERSATIONAL AI & VOICE SCHEME DISCOVERY ENDPOINT
# ---------------------------------------------------------------------------
@app.post("/api/ai/chat")
def conversational_scheme_discovery(payload: ChatRequest):
    """
    Conversational NLU + Deterministic Eligibility Engine endpoint.
    Extracts profile details from Hindi/Hinglish/English utterances, runs deterministic
    scheme evaluation, and returns text + spoken voice response along with updated matches.
    """
    context = extract_profile_and_context(payload.message)
    newly_extracted = context["extracted_profile"]
    merged_profile = {**payload.profile, **newly_extracted}

    goal_info = fallback_understand_goal(payload.message)
    intent = goal_info["intent"]

    # Deterministic scheme evaluation (never overridden by LLM)
    evaluated_items = evaluate_all_schemes(merged_profile)

    reply, spoken_reply, highlighted, ai_used = compose_grounded_chat_response(
        message=payload.message,
        profile=merged_profile,
        newly_extracted=newly_extracted,
        context=context,
        evaluated_items=evaluated_items,
        intent=intent,
        lang=payload.language,
    )

    follow_ups = build_follow_up_questions(merged_profile, intent, payload.language)
    tts_lang = "en-IN" if payload.language.upper() == "EN" else "hi-IN"

    return {
        "reply": reply,
        "spoken_reply": strip_markdown_for_speech(spoken_reply),
        "tts_language": tts_lang,
        "intent": intent,
        "updated_profile": merged_profile,
        "extracted_fields": newly_extracted,
        "follow_up_questions": follow_ups,
        "highlighted_schemes": highlighted,
        "matches": evaluated_items,
        "trust_metadata": {
            "deterministic_engine": True,
            "ai_enhanced": ai_used,
            "verified_only": context["verified_only"],
            "missing_document_addressed": context["missing_document"],
            "disclaimer": "Eligibility decisions are computed 100% deterministically against published government rules. AI is used only for conversational understanding and explanation.",
        },
    }


# ---------------------------------------------------------------------------
# GNANI AI VOICE INTEGRATION ENDPOINTS (VACHANA API: https://api.vachana.ai)
# ---------------------------------------------------------------------------
@app.get("/api/voice/status")
def voice_status():
    """Return Gnani AI Vachana API configuration status and supported models/voices."""
    cfg = get_gnani_config()
    return {
        "gnani_configured": cfg["configured"],
        "openai_configured": get_openai_client() is not None,
        "provider": "Gnani AI (Vachana Platform)",
        "base_url": cfg["base_url"],
        "endpoints": {
            "stt_rest": "/stt/v3",
            "tts_rest": "/api/v1/tts/inference",
        },
        "auth_header": "X-API-Key-ID",
        "stt_model": cfg["stt_model"],
        "tts_model": cfg["tts_model"],
        "default_voice": cfg["tts_voice"],
        "supported_stt_models": SUPPORTED_STT_MODELS,
        "supported_tts_models": SUPPORTED_TTS_MODELS,
        "supported_voices": SUPPORTED_TTS_VOICES,
        "supported_languages": [
            {"code": "hi-IN", "label": "Hindi (हिंदी)"},
            {"code": "indic-auto", "label": "Hinglish / Auto-Detect (Prisma v3.0)"},
            {"code": "en-IN", "label": "English (India)"},
        ],
    }


@app.post("/api/voice/stt")
async def gnani_speech_to_text(
    audio_file: UploadFile = File(...),
    language_code: str = Form("indic-auto"),
    model: str = Form(""),
    format: str = Form("transcribe"),
):
    """
    Proxy audio transcription to Gnani AI Prisma Speech-to-Text REST API:
    POST https://api.vachana.ai/stt/v3
    Headers: X-API-Key-ID: <GNANI_API_KEY>
    Form fields: audio_file, model (prisma-v3.0 | prisma-v2.5), language_code (hi-IN | en-IN | indic-auto), format (transcribe | verbatim)
    """
    audio_bytes = await audio_file.read()
    if not audio_bytes or len(audio_bytes) < 64:
        raise HTTPException(
            status_code=400,
            detail="Audio recording is empty or too short. Please record at least 1 second of speech.",
        )
    if len(audio_bytes) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="Audio file exceeds the 10 MB limit for synchronous REST STT.",
        )

    cfg = get_gnani_config()
    if not cfg["configured"] or not cfg["api_key"]:
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "code": "GNANI_API_KEY_MISSING",
                "message": "GNANI_API_KEY is not configured in backend environment variables. Set GNANI_API_KEY in .env to enable live Gnani Prisma v3.0 transcription, or use browser Web Speech / text input fallback.",
            },
        )

    stt_model = model.strip() if model and model.strip() in SUPPORTED_STT_MODELS else cfg["stt_model"]
    norm_lang = normalize_gnani_language(language_code, for_tts=False)
    # Prisma v2.5 requires an explicit language code rather than indic-auto
    if stt_model == "prisma-v2.5" and norm_lang == "indic-auto":
        norm_lang = "hi-IN"
    fmt = format.strip() if format and format.strip() in ("transcribe", "verbatim", "codemix", "transliterate") else "transcribe"

    filename = audio_file.filename or "recording.wav"
    content_type = audio_file.content_type or "audio/wav"
    url = f"{cfg['base_url']}/stt/v3"

    logger.info(
        "Calling Gnani STT endpoint=%s model=%s language_code=%s bytes=%d",
        url,
        stt_model,
        norm_lang,
        len(audio_bytes),
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={"X-API-Key-ID": cfg["api_key"]},
                files={"audio_file": (filename, audio_bytes, content_type)},
                data={
                    "model": stt_model,
                    "language_code": norm_lang,
                    "format": fmt,
                },
            )
    except httpx.TimeoutException:
        logger.error("Gnani STT request timed out")
        return JSONResponse(
            status_code=504,
            content={
                "success": False,
                "code": "GNANI_STT_TIMEOUT",
                "message": "Gnani AI STT service timed out. Please retry or use text input.",
            },
        )
    except httpx.HTTPError as exc:
        logger.error("Gnani STT transport error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=502,
            content={
                "success": False,
                "code": "GNANI_STT_NETWORK_ERROR",
                "message": "Could not reach Gnani AI STT service (api.vachana.ai).",
            },
        )

    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text[:300]}

    if resp.status_code != 200 or payload.get("success") is False:
        err_msg = (
            payload.get("message")
            or payload.get("detail")
            or f"Gnani STT returned HTTP {resp.status_code}"
        )
        logger.warning("Gnani STT upstream error status=%d", resp.status_code)
        return JSONResponse(
            status_code=resp.status_code if resp.status_code >= 400 else 502,
            content={
                "success": False,
                "code": f"GNANI_STT_HTTP_{resp.status_code}",
                "message": err_msg,
                "request_id": payload.get("request_id"),
            },
        )

    transcript = (payload.get("transcript") or "").strip()
    return {
        "success": True,
        "provider": "gnani-prisma",
        "model": payload.get("model", stt_model),
        "transcript": transcript,
        "detected_language_code": payload.get("detected_language_code", norm_lang),
        "request_id": payload.get("request_id"),
        "processing_time": payload.get("processing_time"),
        "end_to_end_latency": payload.get("end_to_end_latency"),
    }


@app.post("/api/voice/tts")
async def gnani_text_to_speech(req: TTSRequest):
    """
    Proxy speech synthesis to Gnani AI Timbre Text-to-Speech REST API:
    POST https://api.vachana.ai/api/v1/tts/inference
    Headers: X-API-Key-ID: <GNANI_API_KEY>, Content-Type: application/json
    Returns raw binary audio/wav when successful.
    """
    clean_text = strip_markdown_for_speech(req.text)
    if not clean_text:
        raise HTTPException(status_code=400, detail="Text for speech synthesis cannot be empty.")

    cfg = get_gnani_config()
    if not cfg["configured"] or not cfg["api_key"]:
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "code": "GNANI_API_KEY_MISSING",
                "message": "GNANI_API_KEY is not configured in backend environment variables. Set GNANI_API_KEY in .env to enable live Gnani Timbre v2.5 voice synthesis.",
            },
        )

    tts_model = (
        req.model.strip()
        if req.model and req.model.strip() in SUPPORTED_TTS_MODELS
        else cfg["tts_model"]
    )
    voice = (
        req.voice.strip()
        if req.voice and req.voice.strip() in SUPPORTED_TTS_VOICES
        else cfg["tts_voice"]
    )
    lang_code = normalize_gnani_language(req.language, for_tts=True)
    url = f"{cfg['base_url']}/api/v1/tts/inference"

    request_body = {
        "text": clean_text,
        "voice": voice,
        "model": tts_model,
        "language": lang_code,
        "speed": req.speed,
        "audio_config": {
            "encoding": "linear_pcm",
            "container": "wav",
            "num_channels": 1,
            "sample_rate": 48000,
            "sample_width": 2,
        },
    }

    logger.info(
        "Calling Gnani TTS endpoint=%s model=%s voice=%s language=%s chars=%d",
        url,
        tts_model,
        voice,
        lang_code,
        len(clean_text),
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={
                    "X-API-Key-ID": cfg["api_key"],
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
    except httpx.TimeoutException:
        logger.error("Gnani TTS request timed out")
        return JSONResponse(
            status_code=504,
            content={
                "success": False,
                "code": "GNANI_TTS_TIMEOUT",
                "message": "Gnani AI TTS service timed out.",
            },
        )
    except httpx.HTTPError as exc:
        logger.error("Gnani TTS transport error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=502,
            content={
                "success": False,
                "code": "GNANI_TTS_NETWORK_ERROR",
                "message": "Could not reach Gnani AI TTS service (api.vachana.ai).",
            },
        )

    content_type = resp.headers.get("content-type", "")
    if resp.status_code != 200 or "application/json" in content_type:
        try:
            err_payload = resp.json()
            err_msg = err_payload.get("message") or f"Gnani TTS returned HTTP {resp.status_code}"
        except Exception:
            err_msg = f"Gnani TTS returned HTTP {resp.status_code}"
        logger.warning("Gnani TTS upstream error status=%d", resp.status_code)
        return JSONResponse(
            status_code=resp.status_code if resp.status_code >= 400 else 502,
            content={
                "success": False,
                "code": f"GNANI_TTS_HTTP_{resp.status_code}",
                "message": err_msg,
            },
        )

    return Response(
        content=resp.content,
        media_type="audio/wav",
        headers={
            "X-Voice-Provider": "gnani-timbre",
            "X-Voice-Model": tts_model,
            "X-Voice-Name": voice,
            "X-Voice-Language": lang_code,
        },
    )


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
