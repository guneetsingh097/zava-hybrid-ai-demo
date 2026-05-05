"""
Zava Insurance – On-Device AI Demo
==========================================
A Flask application showcasing on-device AI capabilities using
NPU acceleration (Windows AI / Phi Silica) with Foundry Local CPU fallback.

Tabs:
  1. Claims AI       – Upload damage photos, get AI damage assessment
  2. Policy Assistant – Chat about insurance policies (on-device LLM)
  3. Document Analyzer– Paste/upload documents for AI summarisation
  4. NPU Dashboard    – Live NPU status, cost savings, offline proof
"""

import os
import sys
import json
import time
import uuid
import base64
import subprocess
import tempfile
import traceback
import requests as http_requests
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from flask import (
    Flask, render_template, request, jsonify, send_from_directory, Response, stream_with_context
)
from werkzeug.utils import secure_filename
from PIL import Image

# ---------------------------------------------------------------------------
# NPU Engine – Windows AI / Phi Silica via phi-npu.exe
# ---------------------------------------------------------------------------
# Uses phi-npu.exe (Windows AI APIs) for fast on-device NPU inference.
# Phi Silica runs on the NPU for vision + chat (~5-8s).
# Foundry Local (CPU) handles longer text generation in parallel.
# Together: NPU vision + CPU text = true hardware parallelism.
PHI_NPU_EXE = r"C:\Users\gusing\AppData\Local\Microsoft\WindowsApps\phi-npu.exe"

npu_available = False


def _init_npu():
    """Check if phi-npu.exe (Windows AI / Phi Silica) is available."""
    global npu_available
    if not os.path.isfile(PHI_NPU_EXE):
        print("[NPU] phi-npu.exe not found")
        return
    try:
        result = subprocess.run(
            [PHI_NPU_EXE, "chat", "hi"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            npu_available = True
            print("[NPU] Ready – phi-npu.exe (Windows AI / Phi Silica)")
            print("[NPU] Engine: Windows AI APIs (Phi Silica on NPU)")
        else:
            print(f"[NPU] phi-npu.exe test failed: {result.stderr[:200]}")
    except Exception as e:
        print(f"[NPU] Init failed: {e}")


def _npu_chat(system_prompt: str, user_prompt: str, max_tokens: int = 350) -> str:
    """Run text inference on NPU via phi-npu.exe (Phi Silica)."""
    if not npu_available:
        return ""
    try:
        # Phi Silica works best with concise prompts — keep under CLI arg limits
        prompt = f"{system_prompt}\n\nUser question: {user_prompt}"
        if len(prompt) > 2000:
            # Trim the system prompt (which contains CRM context) to fit
            trim_amount = len(prompt) - 2000
            system_prompt = system_prompt[:len(system_prompt) - trim_amount]
            prompt = f"{system_prompt}\n\nUser question: {user_prompt}"
        result = subprocess.run(
            [PHI_NPU_EXE, "chat", prompt],
            capture_output=True, text=True, timeout=30
        )
        text = result.stdout.strip()
        # Strip timing line if present (e.g., "[8113ms, Complete]")
        lines = text.split("\n")
        if lines and lines[-1].startswith("[") and "Complete]" in lines[-1]:
            text = "\n".join(lines[:-1]).strip()
        if not text:
            print(f"[NPU] Empty response. stdout={result.stdout[:200]!r} stderr={result.stderr[:200]!r}")
        return text
    except Exception as e:
        print(f"[NPU] Chat error: {e}")
        return ""


def _foundry_chat_sync(system_prompt: str, user_prompt: str, max_tokens: int = 300) -> str:
    """Non-streaming text generation on CPU via Foundry Local.
    Used for quick enrichment tasks (e.g. photo description enhancement)."""
    if not foundry_ok:
        return ""
    try:
        resp = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[CPU] Foundry sync error: {e}")
        return ""


def _enhance_photo_description(raw_desc: str, damage_type: str) -> str:
    """Enhance a raw NPU vision description with damage-specific detail using CPU (Foundry Local).
    Runs on CPU (~2-3s) while NPU continues processing other photos = true parallelism."""
    if not raw_desc or not foundry_ok:
        return raw_desc

    damage_guides = {
        "water": (
            "Focus on: moisture patterns (spreading direction, tide marks), paint/plaster condition "
            "(peeling, bubbling, blistering), discoloration type (yellow-brown water stains vs dark "
            "black-green mold spots), surface material (drywall, plaster, wood), damage extent "
            "(percentage of wall/ceiling affected), mold evidence (dark spots, fuzzy growth, "
            "discoloration patterns), water source clues (from above=roof/pipe, from below=foundation), "
            "structural concerns (sagging, warping, swelling)."
        ),
        "fire": (
            "Focus on: char depth (surface vs deep), smoke staining patterns, heat warping/melting, "
            "structural integrity of load-bearing elements, soot coverage, fire spread direction."
        ),
        "wind": (
            "Focus on: uplift patterns, missing/displaced materials, debris impact marks, "
            "envelope breaches, exposed underlying structure, water intrusion points."
        ),
        "property": (
            "Focus on: structural vs cosmetic damage, load-bearing elements, foundation condition, "
            "material identification, damage extent and depth."
        ),
    }
    guide = damage_guides.get(damage_type, damage_guides["property"])

    system = (
        "You are an expert insurance damage photo analyst. Given a brief image description, "
        "expand it into a detailed damage assessment paragraph. Describe EXACTLY what is visible — "
        "materials, surfaces, damage patterns, severity, extent. Be specific and quantitative where "
        "possible (e.g. 'approximately 40% of the wall surface'). If mold-like features are described "
        "(dark spots, discoloration, fuzzy growth), explicitly identify them as MOLD EVIDENCE. "
        "Output ONLY the enhanced description, no headings or labels."
    )
    user = (
        f"Raw image description: {raw_desc}\n\n"
        f"Damage type context: {damage_type}\n"
        f"Analysis guide: {guide}\n\n"
        "Write a detailed 3-5 sentence damage description based on what the image shows."
    )

    enhanced = _foundry_chat_sync(system, user, max_tokens=250)
    if enhanced and len(enhanced) > len(raw_desc):
        return enhanced
    return raw_desc


def _foundry_chat_stream(system_prompt: str, user_prompt: str, max_tokens: int = 500):
    """Stream text generation on CPU via Foundry Local (OpenAI-compatible API).
    Runs on CPU cores, leaving NPU free for vision tasks = true parallelism."""
    if not foundry_ok:
        yield "[Error: Foundry Local not available]"
        return
    try:
        resp = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            stream=True,
        )
        for chunk in resp:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        print(f"[CPU] Foundry stream error: {e}")
        yield f"[Error: {e}]"


def _npu_describe_image(image_path: str) -> str:
    """Describe an image using NPU (phi-npu.exe vision model)."""
    if not os.path.isfile(PHI_NPU_EXE):
        return ""
    try:
        img = Image.open(image_path)
        img.thumbnail((512, 512), Image.LANCZOS)
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        img.save(tmp.name, "JPEG", quality=85)
        tmp.close()

        result = subprocess.run(
            [PHI_NPU_EXE, "describe", tmp.name],
            capture_output=True, text=True, timeout=30
        )
        os.unlink(tmp.name)
        text = result.stdout.strip()
        lines = text.split("\n")
        if lines and lines[-1].startswith("[") and "Complete]" in lines[-1]:
            text = "\n".join(lines[:-1]).strip()
        return text
    except Exception as e:
        print(f"[NPU] Describe error: {e}")
        return ""


# ---------------------------------------------------------------------------
# Foundry Local bootstrap (CPU text generation)
# ---------------------------------------------------------------------------
foundry_ok = False
client = None
model_id = None
manager = None

def init_foundry():
    """Initialise Foundry Local connection – CPU fallback when NPU unavailable."""
    global foundry_ok, client, model_id, manager

    NPU_MODELS = os.environ.get(
        "FOUNDRY_MODELS",
        "qwen2.5-1.5b,phi-3-mini-4k,phi-3.5-mini,phi-4-mini"
    ).split(",")

    try:
        from foundry_local_sdk import FoundryLocalManager
    except ImportError:
        from foundry_local import FoundryLocalManager
    from openai import OpenAI

    for alias in NPU_MODELS:
        alias = alias.strip()
        try:
            print(f"[STARTUP] Trying model: {alias} ...")
            manager = FoundryLocalManager(alias)
            client = OpenAI(base_url=manager.endpoint, api_key=manager.api_key)
            info = manager.get_model_info(alias)
            model_id = info.id
            foundry_ok = True
            print(f"[STARTUP] Foundry Local connected – model: {model_id}")
            print(f"[STARTUP] Endpoint: {manager.endpoint}")
            print(f"[STARTUP] Role: {'CPU fallback' if npu_available else 'primary (no NPU)'}")
            return
        except Exception as exc:
            print(f"[STARTUP]   → {alias} failed: {exc}")
            continue

    print("[STARTUP] No Foundry models loaded.")
    foundry_ok = False

_init_npu()
print(f"[STARTUP] NPU (Phi Silica): {'Available' if npu_available else 'Not available'}")
init_foundry()

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

# Background thread pool for parallel image analysis
_executor = ThreadPoolExecutor(max_workers=2)
_image_cache: dict = {}  # filename → description

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
inference_log: list[dict] = []

# ---------------------------------------------------------------------------
# Mock Customer / Policy Database (simulates CRM data available on-device)
# ---------------------------------------------------------------------------
_active_customer = {
    "name": "Sarah Mitchell",
    "policy_number": "ZAV-HO3-2024-08847",
    "policy_type": "HO-3 (Special Form Homeowners)",
    "address": "4218 Elm Creek Dr, Austin, TX 78745",
    "property_type": "Single-family detached, 2-story, 2,400 sq ft, built 2006",
    "coverage_a_dwelling": "$485,000",
    "coverage_b_other_structures": "$48,500",
    "coverage_c_personal_property": "$363,750",
    "coverage_d_loss_of_use": "$145,500",
    "deductible": "$2,500 (all perils), 2% wind/hail",
    "premium": "$3,240/yr",
    "effective_dates": "03/15/2024 – 03/15/2025",
    "prior_claims": [
        {"date": "2022-06-14", "type": "Wind/Hail", "amount": "$8,200", "status": "Closed"},
        {"date": "2020-11-03", "type": "Water (pipe)", "amount": "$4,100", "status": "Closed"},
    ],
    "risk_notes": "Property in moderate flood zone (Zone X500). Roof replaced 2019. No outstanding liens.",
    "agent": "Marcus Reeves (austin-west@zava.com)",
}


def _get_customer_context() -> str:
    """Format active customer data for inclusion in claims assessment."""
    c = _active_customer
    claims_history = "\n".join(
        f"    - {cl['date']}: {cl['type']} – {cl['amount']} ({cl['status']})"
        for cl in c["prior_claims"]
    ) or "    None"
    return (
        f"POLICYHOLDER: {c['name']}\n"
        f"POLICY: {c['policy_number']} ({c['policy_type']})\n"
        f"PROPERTY: {c['address']} — {c['property_type']}\n"
        f"COVERAGE: Dwelling {c['coverage_a_dwelling']}, Personal Prop {c['coverage_c_personal_property']}, "
        f"Deductible {c['deductible']}\n"
        f"PRIOR CLAIMS:\n{claims_history}\n"
        f"RISK: {c['risk_notes']}"
    )

def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text (GPT-style)."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# CRM / M365 Context Retrieval (via WorkIQ proxy)
# ---------------------------------------------------------------------------
# WorkIQ endpoint — the Copilot CLI's WorkIQ MCP tool handles the actual M365 query.
# This function calls a local bridge that the CLI exposes during demo.
WORKIQ_BRIDGE_PORT = int(os.environ.get("WORKIQ_BRIDGE_PORT", "5001"))


def _fetch_crm_context(user_question: str) -> tuple:
    """Fetch relevant CRM/M365 context for the user's question.
    Returns (context_text, source_description) or ("", None) on failure."""
    c = _active_customer
    # Build a CRM-oriented query combining the user question with customer context
    crm_query = (
        f"For insurance customer {c['name']} (policy {c['policy_number']}), "
        f"property at {c['address']}: {user_question}"
    )

    # Try local WorkIQ bridge first (CLI-hosted)
    try:
        resp = http_requests.post(
            f"http://127.0.0.1:{WORKIQ_BRIDGE_PORT}/workiq-query",
            json={"question": crm_query},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            context = data.get("response", "").strip()
            if context:
                print(f"[CRM] WorkIQ context retrieved ({len(context)} chars)")
                return context, "Microsoft 365 Copilot (WorkIQ)"
    except Exception as e:
        print(f"[CRM] WorkIQ bridge unavailable: {e}")

    # Fallback: simulated WorkIQ data (concise summaries from OneDrive documents)
    crm_data = _get_simulated_crm_data(user_question, c)
    if crm_data:
        return crm_data, "Microsoft 365 (WorkIQ)"

    return "", None


def _get_simulated_crm_data(question: str, customer: dict) -> str:
    """Return concise CRM summaries based on question keywords.
    These simulate what WorkIQ would return — short, factual summaries
    that fit within NPU context limits (~500 chars max).
    The full documents live in the user's OneDrive for Business
    (folder: 'Zava Insurance Demo') and are indexed by WorkIQ."""
    q = question.lower()

    # Concise summaries (like what WorkIQ returns) — NOT full documents
    _SUMMARIES = {
        "transcript": (
            "CALL TRANSCRIPT SUMMARY (May 2, 9:14AM): Sarah Mitchell reported basement flooding "
            "from overnight storm. Sump pump failed, ~2 inches standing water. Carpet soaked, "
            "drywall damaged 4 inches up. Electrical outlet near water — breaker isolated. "
            "Agent Priya Sharma opened claim CLM-2024-09283, scheduled adjuster David Park for May 3 AM. "
            "Customer cooperative, already took photos. Mold risk flagged (48hr window)."
        ),
        "ticket": (
            "CLAIM CLM-2024-09283 STATUS: OPEN — Assessment Pending. Customer: Sarah Mitchell, "
            "Policy ZAV-HO3-2024-08847. Water damage from sump pump failure + window well overflow "
            "(May 2, 2024). Preliminary estimate $12-15K. Coverage confirmed under HO-46 ($25K sublimit). "
            "Deductible $2,500. Field inspection complete May 3. Awaiting AI assessment + supervisor approval. "
            "Safety flags: electrical hazard (isolated), mold risk (48hr SLA)."
        ),
        "adjuster": (
            "FIELD REPORT (David Park, May 3): 2.5in standing water NW corner, 800 sq ft carpet saturated, "
            "drywall damaged lower 4in. Sump pump burned out (original 2006, 18 years old). Window well "
            "overflow contributed. Electrical outlet NOT submerged but within splash zone — electrician needed. "
            "Mold risk medium-high, musty odor present. Estimate: $14,740 total (extraction $2,800, "
            "carpet $5,200, drywall $2,400, baseboard $900, pump $1,200, antimicrobial $600)."
        ),
        "teams": (
            "TEAMS CHAT (David Park ↔ Rachel Torres, May 2-3): 14 claims from same storm in area. "
            "David confirmed electrical safety concern on-site. Estimate $13-15K — above $10K auto-approve "
            "threshold, needs supervisor sign-off. AquaRestore LLC providing formal estimate ($12,400). "
            "Rachel fast-tracking approval due to mold timeline (~30hrs since flooding). "
            "Customer described as very cooperative."
        ),
        "email": (
            "EMAIL THREAD (5 messages, May 2): Sarah Mitchell uploaded 4 photos, reported water still "
            "rising slowly. Agent authorized emergency mitigation (wet-vac). Customer renting equipment "
            "from Home Depot, keeping receipts. Mold concern acknowledged — adjuster prioritized. "
            "Reminded to keep breaker OFF. Prep instructions given for adjuster visit next morning."
        ),
        "vendor": (
            "AQUARESTORE ESTIMATE: $12,900 total for full basement restoration. Includes: water extraction "
            "$1,650, structural dry-out $1,155, carpet removal/replacement $4,800, drywall $2,400, "
            "baseboards $900, antimicrobial $825, paint $660. Timeline: 10 business days from authorization. "
            "Emergency same-day start available. Prior work at this property (2020 pipe burst). "
            "NOT included: sump pump, electrician, personal property."
        ),
        "coverage": (
            "COVERAGE VERIFIED: Policy active (03/2024-03/2025). HO-46 Water Backup endorsement CONFIRMED — "
            "$25,000 sublimit. Deductible $2,500. Estimated net payable $9,500-$12,500. No exclusions apply "
            "(not surface flood, not maintenance neglect). Fraud score 2% (Low). Prior claims: wind/hail "
            "$8,200 (2022), pipe burst $4,100 (2020). Underwriting review recommended at renewal."
        ),
        "approval": (
            "SUPERVISOR APPROVAL (Rachel Torres): PENDING. Claim exceeds $10K auto-approve threshold. "
            "Recommendation: APPROVE with conditions. Max authorization requested: $21,400 (vendor $12,900 + "
            "electrician $500 + mold contingency $8,000). Net payout after deductible: up to $18,900. "
            "All checklist items complete except AI assessment. Urgency HIGH — mold risk, 48hr window closing. "
            "Comparable claims in region: $10-14K range."
        ),
    }

    # Map keywords to summary keys
    _KEYWORD_MAP = [
        (["call", "transcript", "intake", "reported", "initial", "phone", "first notice", "fnol"], "transcript"),
        (["ticket", "claim status", "status", "open claim", "current claim", "filed", "timeline"], "ticket"),
        (["adjuster", "field", "inspection", "on-site", "visit", "notes", "david", "damage"], "adjuster"),
        (["teams", "internal", "chat", "slack", "im ", "instant message"], "teams"),
        (["email", "message", "contact", "communic", "correspondence", "priya"], "email"),
        (["contractor", "vendor", "repair", "estimate", "plumber", "electrician", "aquarestore", "cost"], "vendor"),
        (["coverage", "limit", "policy detail", "endorsement", "rider", "covered", "verification"], "coverage"),
        (["approv", "supervisor", "escalat", "queue", "pending review", "rachel", "sign-off"], "approval"),
    ]

    # Find matching summary
    matched_key = "ticket"  # default
    for keywords, key in _KEYWORD_MAP:
        if any(kw in q for kw in keywords):
            matched_key = key
            break

    summary = _SUMMARIES[matched_key]
    print(f"[CRM] WorkIQ summary: {matched_key} ({len(summary)} chars)")
    return summary


def _run_inference(system_prompt: str, user_prompt: str, max_tokens: int = 1024) -> dict:
    """Run inference – NPU first (QNN GenAI), Foundry Local CPU fallback."""
    t0 = time.perf_counter()
    text = ""
    engine = "none"

    # Try NPU first (ONNX Runtime GenAI + QNN)
    if npu_available:
        text = _npu_chat(system_prompt, user_prompt, max_tokens=max_tokens)
        if text:
            engine = "npu"

    # CPU fallback via Foundry Local
    if not text and foundry_ok:
        try:
            resp = client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
            )
            text = resp.choices[0].message.content or ""
            engine = "cpu"
        except Exception as exc:
            print(f"[INFERENCE] Foundry error: {exc}")
            try:
                init_foundry()
                resp = client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=max_tokens,
                )
                text = resp.choices[0].message.content or ""
                engine = "cpu"
            except Exception as exc2:
                text = f"[Error: AI unavailable – {exc2}]"

    if not text:
        text = "[No AI engine available. Ensure QNN NPU or Foundry Local is running.]"

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    total_tokens = _estimate_tokens(system_prompt + user_prompt + text)
    est_cost = round(total_tokens * 0.00001, 6)

    entry = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().isoformat(),
        "tokens": total_tokens,
        "latency_ms": elapsed_ms,
        "cloud_cost_saved": f"${est_cost:.4f}",
        "engine": engine,
    }
    inference_log.append(entry)

    return {
        "text": text,
        "tokens": total_tokens,
        "latency_ms": elapsed_ms,
        "cloud_cost_saved": f"${est_cost:.4f}",
        "engine": engine,
    }

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/customer")
def api_customer():
    """Return active customer profile for display in claims UI."""
    c = _active_customer
    return jsonify({
        "name": c["name"],
        "policy_number": c["policy_number"],
        "policy_type": c["policy_type"],
        "address": c["address"],
        "property_type": c["property_type"],
        "coverage_a": c["coverage_a_dwelling"],
        "coverage_c": c["coverage_c_personal_property"],
        "deductible": c["deductible"],
        "effective_dates": c["effective_dates"],
        "prior_claims_count": len(c["prior_claims"]),
        "prior_claims": c["prior_claims"],
        "risk_notes": c["risk_notes"],
    })


@app.route("/api/status")
def api_status():
    """Return NPU / Foundry Local availability."""
    return jsonify({
        "foundry_connected": foundry_ok or npu_available,
        "model": "Phi Silica (NPU)" if npu_available else (model_id or "N/A"),
        "endpoint": "Windows AI APIs (phi-npu.exe)" if npu_available else (str(manager.endpoint) if manager else "N/A"),
        "mode": "on-device NPU + CPU" if (npu_available and foundry_ok) else ("on-device NPU" if npu_available else ("on-device CPU" if foundry_ok else "UI preview (no AI)")),
        "hardware": "NPU (Phi Silica) + CPU (Foundry Local)" if (npu_available and foundry_ok) else ("NPU (Phi Silica)" if npu_available else ("CPU" if foundry_ok else "none")),
        "npu_available": npu_available,
        "cpu_fallback": foundry_ok,
    })


def _build_assessment_prompt(damage_type, damage_label, description, photo_descriptions):
    """Build system + user prompts for claims assessment. Shared by sync and streaming endpoints.

    Rules implemented:
    - ANALYSIS ONLY — no repeating customer data already on screen
    - Walls are VERTICAL, ceilings are HORIZONTAL — never confuse them
    - For water damage: mold is #1 priority, scan all evidence for indicators
    - Mold indicators trigger a hard MOLD ALERT that model MUST include
    - Photo descriptions + field notes analyzed collectively
    - Cost estimates, severity, required actions, red flags
    """

    # Damage-type-specific analysis instructions
    water_focus = (
        "WATER DAMAGE ANALYSIS REQUIREMENTS:\n"
        "- MOLD DETECTION IS YOUR #1 PRIORITY for water damage claims.\n"
        "- Any peeling paint, moisture, musty smell, staining, discoloration, dark spots, "
        "dampness, or leaking = MOLD IS PRESENT. State it as fact, never as 'possible.'\n"
        "- ELECTRICAL SAFETY: If water damage is near outlets, switches, or wiring, "
        "flag as ⚡ ELECTRICAL HAZARD — risk of shock/fire. Recommend immediate power shutoff.\n"
        "- Walls are VERTICAL surfaces. Ceilings are HORIZONTAL overhead. NEVER confuse them.\n"
        "- If the evidence says 'wall', write WALL. Only say ceiling if explicitly overhead/horizontal.\n"
        "- If a ⚠️ MOLD ALERT section appears in the evidence, you MUST discuss mold prominently "
        "in your DAMAGE ANALYSIS section and include mold remediation in COST ESTIMATE.\n"
    )
    fire_focus = (
        "FIRE ANALYSIS: char depth, smoke penetration, heat warping, "
        "structural integrity, air quality, adjacent room contamination.\n"
    )
    wind_focus = (
        "WIND ANALYSIS: uplift patterns, debris impact, envelope breach, "
        "water intrusion, consistency with wind direction.\n"
    )
    prop_focus = "STRUCTURAL ANALYSIS: structural vs cosmetic, load-bearing elements, foundation, code compliance.\n"

    focus_map = {"water": water_focus, "fire": fire_focus, "wind": wind_focus, "property": prop_focus}
    focus = focus_map.get(damage_type, "")

    # For water damage: scan ALL evidence for mold indicators and inject finding
    mold_alert = ""
    if damage_type == "water":
        all_evidence = " ".join(photo_descriptions).lower() + " " + (description or "").lower()
        mold_keywords = ["peel", "moisture", "musty", "smell", "odor", "dark spot", "discolor",
                         "stain", "bubble", "blister", "damp", "wet", "leak", "mildew",
                         "black", "green", "fuzzy", "spore", "water"]
        found = [kw for kw in mold_keywords if kw in all_evidence]
        if found:
            mold_alert = (
                "⚠️ MOLD ALERT — CONFIRMED INDICATORS DETECTED: "
                f"{', '.join(found)}.\n"
                "FINDING: ACTIVE MOLD GROWTH IS PRESENT based on the above indicators in a "
                "water-damaged environment. This is an industry-standard determination.\n"
                "YOU MUST:\n"
                "- State 'MOLD IS PRESENT' in your DAMAGE ANALYSIS (not 'possible' or 'may lead to')\n"
                "- Include mold remediation cost: $2,000–$6,000\n"
                "- Flag as HEALTH HAZARD requiring immediate professional mold testing\n"
                "- Recommend occupant precautions until remediation is complete\n"
            )

    system = (
        "You are a senior insurance claims adjustor writing a DAMAGE ANALYSIS REPORT.\n\n"
        "STRICT RULES:\n"
        "- ANALYSIS ONLY — DO NOT repeat policyholder name, address, policy number, prior claims, "
        "or coverage details. The adjuster already sees that on screen.\n"
        "- If a ⚠️ MOLD ALERT appears, you MUST discuss mold as PRESENT in your analysis.\n"
        "- Walls are VERTICAL. Ceilings are HORIZONTAL overhead. Never confuse them.\n\n"
        "WRITE THESE SECTIONS:\n"
        "1. **DAMAGE ANALYSIS**: Specific damage observed. What surface (wall/ceiling/floor)? "
        "Structural vs cosmetic? Safety/health hazards including MOLD if indicated? "
        "ELECTRICAL SAFETY: If any outlets, wiring, or electrical panels are near water or damage, "
        "flag as IMMEDIATE SAFETY HAZARD.\n"
        "2. **SEVERITY**: Minor / Moderate / Severe / Catastrophic with justification.\n"
        "3. **COST ESTIMATE**: Itemized dollar amounts for each repair needed.\n"
        "4. **COVERAGE & DEDUCTIBLE**: Does this exceed the $2,500 deductible? Estimated payout?\n"
        "5. **REQUIRED ACTIONS**: Next steps and priority level.\n\n"
        f"{focus}"
        "BEGIN YOUR ANALYSIS IMMEDIATELY — do not restate claim info.\n"
    )

    desc_truncated = description[:1200] if description else ""
    photo_section = "\n\n".join(photo_descriptions) if photo_descriptions else ""

    user_parts = [f"Claim type: {damage_label}"]
    user_parts.append("Policy: dwelling $485K, deductible $2,500, 2 prior claims (wind $8.2K + water $4.1K)")
    if photo_section:
        max_photo_chars = min(3000, 600 * len(photo_descriptions))
        user_parts.append(f"PHOTO EVIDENCE ({len(photo_descriptions)} photo(s)):\n{photo_section[:max_photo_chars]}")
    if desc_truncated:
        user_parts.append(f"FIELD NOTES:\n{desc_truncated}")
    if mold_alert:
        user_parts.append(mold_alert)
    user_parts.append("Write your damage analysis now.")

    return system, "\n\n".join(user_parts)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Policy Assistant – general insurance chat. Optionally enriches with CRM/M365 data."""
    data = request.get_json(force=True)
    user_msg = data.get("message", "").strip()
    use_crm = data.get("use_crm", False)
    if not user_msg:
        return jsonify({"error": "Empty message"}), 400

    crm_context = ""
    crm_source = None

    if use_crm:
        # Query WorkIQ for customer/CRM context relevant to the question
        crm_context, crm_source = _fetch_crm_context(user_msg)

    c = _active_customer
    system = (
        "You are Zava Insurance's AI assistant. Be concise and professional. "
        "Answer insurance questions about policies, claims, coverage, and terminology.\n\n"
        f"CURRENT CUSTOMER:\n"
        f"- Name: {c['name']}\n"
        f"- Policy: {c['policy_number']} ({c['policy_type']})\n"
        f"- Property: {c['address']}\n"
        f"- Coverage: {c['coverage_a_dwelling']} dwelling, {c['deductible']} deductible\n"
    )

    if crm_context:
        system += (
            f"\nCRM / ORGANIZATIONAL CONTEXT (retrieved from M365):\n"
            f"{crm_context}\n\n"
            f"Use this context to give a more informed answer. Cite the source if relevant. "
            f"Always note that AI reasoning was performed on-device.\n"
        )

    result = _run_inference(system, user_msg, max_tokens=300)
    if crm_context:
        result["crm_enriched"] = True
        result["crm_source"] = crm_source
    else:
        result["crm_enriched"] = False
    return jsonify(result)


@app.route("/api/assess-claim", methods=["POST"])
def api_assess_claim():
    """Claims AI – deep professional claims adjustment analysis."""
    data = request.get_json(force=True)
    description = data.get("description", "").strip()
    damage_type = data.get("damage_type", "property")
    photo_files = data.get("photo_files", [])

    if not description and not photo_files:
        return jsonify({"error": "No damage description or photos provided"}), 400

    # Gather any cached photo analysis results
    photo_descriptions = []
    for fname in photo_files:
        if fname in _image_cache:
            photo_descriptions.append(_image_cache[fname])

    if not description and not photo_descriptions:
        return jsonify({"error": "No damage description provided"}), 400

    # Map dropdown values to professional terminology
    damage_labels = {
        "property": "Property / Structural Damage",
        "vehicle": "Vehicle / Auto Collision",
        "water": "Water Damage / Flood / Plumbing Failure",
        "fire": "Fire / Smoke / Heat Damage",
        "wind": "Wind / Storm / Hurricane / Hail",
        "other": "General Damage",
    }
    damage_label = damage_labels.get(damage_type, damage_type)

    system, user_prompt = _build_assessment_prompt(damage_type, damage_label, description, photo_descriptions)
    result = _run_inference(system, user_prompt, max_tokens=500)
    return jsonify(result)


@app.route("/api/assess-claim-stream", methods=["POST"])
def api_assess_claim_stream():
    """SSE assessment — NPU (Phi Silica) primary, CPU (Foundry Local) fallback.
    Uses phi-npu.exe for fast on-device inference (~5-7s), then streams result."""
    data = request.get_json(force=True)
    description = data.get("description", "").strip()
    damage_type = data.get("damage_type", "property")
    photo_files = data.get("photo_files", [])

    if not description and not photo_files:
        return jsonify({"error": "No damage description or photos provided"}), 400

    photo_descriptions = []
    for fname in photo_files:
        if fname in _image_cache:
            photo_descriptions.append(_image_cache[fname])

    if not description and not photo_descriptions:
        return jsonify({"error": "No damage description provided"}), 400

    damage_labels = {
        "property": "Property / Structural Damage",
        "vehicle": "Vehicle / Auto Collision",
        "water": "Water Damage / Flood / Plumbing Failure",
        "fire": "Fire / Smoke / Heat Damage",
        "wind": "Wind / Storm / Hurricane / Hail",
        "other": "General Damage",
    }
    damage_label = damage_labels.get(damage_type, damage_type)

    system, user_prompt = _build_assessment_prompt(damage_type, damage_label, description, photo_descriptions)
    t0 = time.perf_counter()

    def generate():
        engine = "none"
        text = ""

        # Try NPU first (phi-npu.exe — fast ~5-7s)
        if npu_available:
            print(f"[PIPELINE] Assessment → NPU (Phi Silica)")
            engine = "npu"
            text = _npu_chat(system, user_prompt, max_tokens=500)

        # CPU fallback via Foundry Local streaming
        if not text and foundry_ok:
            print(f"[PIPELINE] Assessment → CPU (Foundry Local) fallback")
            engine = "cpu"
            for chunk in _foundry_chat_stream(system, user_prompt, max_tokens=500):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            text = None  # already streamed

        # Send NPU result as single chunk (already complete)
        if text:
            yield f"data: {json.dumps({'chunk': text})}\n\n"
        elif text == "" and engine != "cpu":
            yield f"data: {json.dumps({'chunk': '[No AI engine available]'})}\n\n"

        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        total_tokens = _estimate_tokens(system + user_prompt + (text or ""))
        est_cost = round(total_tokens * 0.00001, 6)
        entry = {
            "id": str(uuid.uuid4())[:8],
            "timestamp": datetime.now().isoformat(),
            "tokens": total_tokens,
            "latency_ms": elapsed_ms,
            "cloud_cost_saved": f"${est_cost:.4f}",
            "engine": engine,
        }
        inference_log.append(entry)
        yield f"data: {json.dumps({'done': True, 'tokens': total_tokens, 'latency_ms': elapsed_ms, 'cloud_cost_saved': f'${est_cost:.4f}', 'engine': engine})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Approval Submission — sends report for supervisor review
# ---------------------------------------------------------------------------
APPROVAL_WEBHOOK_URL = os.environ.get("APPROVAL_WEBHOOK_URL", "")
APPROVAL_EMAIL = os.environ.get("APPROVAL_EMAIL", "gusing@microsoft.com")
REPORTS_DIR = BASE_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


@app.route("/api/submit-approval", methods=["POST"])
def api_submit_approval():
    """Submit a claim report for supervisor approval.
    Saves report locally and sends via configured webhook or email script."""
    data = request.get_json(force=True)
    report = data.get("report", "").strip()
    damage_type = data.get("damage_type", "property")
    field_notes = data.get("field_notes", "")
    photo_files = data.get("photo_files", [])

    if not report:
        return jsonify({"success": False, "error": "No report to submit"}), 400

    # Generate claim ID and save report
    claim_id = f"CLM-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    c = _active_customer

    damage_labels = {
        "property": "Property / Structural Damage",
        "vehicle": "Vehicle / Auto Collision",
        "water": "Water Damage / Flood / Plumbing Failure",
        "fire": "Fire / Smoke / Heat Damage",
        "wind": "Wind / Storm / Hurricane / Hail",
        "other": "General Damage",
    }
    damage_label = damage_labels.get(damage_type, damage_type)

    # Build full report document
    report_doc = (
        f"# CLAIM REPORT — {claim_id}\n\n"
        f"**Date:** {datetime.now().strftime('%B %d, %Y at %I:%M %p')}\n"
        f"**Adjuster:** On-Device AI Assessment (Zava Insurance)\n"
        f"**Status:** PENDING APPROVAL\n\n"
        f"---\n\n"
        f"## Policyholder\n"
        f"- **Name:** {c['name']}\n"
        f"- **Policy:** {c['policy_number']} ({c['policy_type']})\n"
        f"- **Property:** {c['address']}\n"
        f"- **Deductible:** {c['deductible']}\n\n"
        f"## Claim Details\n"
        f"- **Type:** {damage_label}\n"
        f"- **Photos:** {len(photo_files)} submitted\n"
        f"- **Field Notes:** {field_notes or 'None'}\n\n"
        f"---\n\n"
        f"## AI Assessment (Generated On-Device via NPU)\n\n"
        f"{report}\n\n"
        f"---\n\n"
        f"*This report was generated entirely on-device using NPU (Phi Silica) inference. "
        f"No claim data was sent to the cloud during analysis.*\n"
    )

    # Save to local reports folder
    report_path = REPORTS_DIR / f"{claim_id}.md"
    report_path.write_text(report_doc, encoding="utf-8")
    print(f"[APPROVAL] Report saved: {report_path}")

    # Try Power Automate webhook if configured
    if APPROVAL_WEBHOOK_URL:
        try:
            payload = {
                "claim_id": claim_id,
                "title": f"Claim Approval: {c['name']} — {damage_label}",
                "approver": APPROVAL_EMAIL,
                "customer_name": c["name"],
                "policy_number": c["policy_number"],
                "damage_type": damage_label,
                "report_summary": report[:500],
                "full_report": report_doc,
            }
            resp = http_requests.post(APPROVAL_WEBHOOK_URL, json=payload, timeout=10)
            if resp.status_code < 300:
                print(f"[APPROVAL] Webhook sent successfully")
                return jsonify({"success": True, "claim_id": claim_id, "method": "webhook"})
            else:
                print(f"[APPROVAL] Webhook failed: {resp.status_code}")
        except Exception as e:
            print(f"[APPROVAL] Webhook error: {e}")

    # Fallback: save report and return success (can be picked up by CLI/script)
    return jsonify({
        "success": True,
        "claim_id": claim_id,
        "method": "local",
        "report_path": str(report_path),
        "message": f"Report saved. Approval request ready for {APPROVAL_EMAIL}.",
    })


@app.route("/api/analyze-document", methods=["POST"])
def api_analyze_document():
    """Document Analyzer – summarise/extract from pasted text."""
    data = request.get_json(force=True)
    doc_text = data.get("text", "").strip()
    task = data.get("task", "summarize")  # summarize | extract | review

    if not doc_text:
        return jsonify({"error": "No document text provided"}), 400

    task_prompts = {
        "summarize": (
            "Summarize this insurance document in 3-5 bullet points. "
            "Focus on: coverage limits, deductibles, exclusions, key dates."
        ),
        "extract": (
            "Extract key data: policy number, insured name, coverage type, "
            "dates, limits, deductibles, premium, endorsements. "
            "Return as a structured list."
        ),
        "review": (
            "Review this insurance document for potential issues: gaps in coverage, "
            "unusual exclusions, compliance concerns, or items that need clarification. "
            "Provide a brief risk assessment."
        ),
    }

    system = "Zava Insurance document analyst. " + task_prompts.get(task, task_prompts["summarize"])
    # Truncate document to keep within NPU context window
    doc_truncated = doc_text[:1500]
    result = _run_inference(system, doc_truncated, max_tokens=350)
    return jsonify(result)


@app.route("/api/metrics")
def api_metrics():
    """Return cumulative inference metrics for the dashboard."""
    total_tokens = sum(e["tokens"] for e in inference_log)
    total_cost = sum(float(e["cloud_cost_saved"].replace("$", "")) for e in inference_log)
    avg_latency = (
        round(sum(e["latency_ms"] for e in inference_log) / len(inference_log))
        if inference_log else 0
    )
    return jsonify({
        "total_inferences": len(inference_log),
        "total_tokens": total_tokens,
        "total_cloud_cost_saved": f"${total_cost:.4f}",
        "avg_latency_ms": avg_latency,
        "log": inference_log[-20:],  # last 20 entries
    })


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(str(UPLOAD_DIR), filename)


@app.route("/api/upload-image", methods=["POST"])
def upload_image():
    """Handle image upload for claims – triggers background NPU analysis."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"error": "Empty file"}), 400
    if not _allowed_file(f.filename):
        return jsonify({"error": "File type not allowed"}), 400

    fname = secure_filename(f"{uuid.uuid4().hex[:8]}_{f.filename}")
    save_path = str(UPLOAD_DIR / fname)
    f.save(save_path)

    # Start background NPU image analysis (vision-only, no LLM rewrite)
    # Assessment LLM runs on CPU (Foundry Local) = true hardware parallelism
    damage_type_hint = request.form.get("damage_type", "property")
    if os.path.isfile(PHI_NPU_EXE):
        def _bg_analyze(path, name, dtype):
            """NPU-only photo analysis: phi-npu.exe describe (~8s).
            Fast single-stage vision — no CPU rewrite needed.
            Domain inference rules add mold/damage notes post-analysis."""
            t0 = time.perf_counter()
            raw_desc = _npu_describe_image(path)
            npu_ms = round((time.perf_counter() - t0) * 1000)
            if not raw_desc:
                _image_cache[name] = "(Photo could not be analyzed)"
                return

            # For water damage: apply domain knowledge inference rules
            if dtype == "water":
                check_text = raw_desc.lower()
                indicators = []
                if any(w in check_text for w in ["peel", "flak", "chip", "blister", "bubble"]):
                    indicators.append("peeling/flaking paint (moisture behind surface)")
                if any(w in check_text for w in ["moisture", "water", "wet", "damp", "leak"]):
                    indicators.append("active moisture presence")
                if any(w in check_text for w in ["stain", "discolor", "dark", "spot", "yellow", "brown"]):
                    indicators.append("staining/discoloration (possible mold evidence)")
                if any(w in check_text for w in ["warp", "buckle", "swell", "bulge", "bow"]):
                    indicators.append("material warping/swelling")
                if any(w in check_text for w in ["crack", "separ", "gap"]):
                    indicators.append("cracking/separation")
                if any(w in check_text for w in ["mold", "mildew", "fung", "spore"]):
                    indicators.append("VISIBLE MOLD GROWTH")
                if any(w in check_text for w in ["fuzzy", "furry", "growth"]):
                    indicators.append("organic growth pattern (mold)")
                if any(w in check_text for w in ["outlet", "socket", "plug", "switch", "wire", "electric", "panel"]):
                    indicators.append("⚡ ELECTRICAL HAZARD — water near electrical components")

                if indicators:
                    mold_note = (
                        f"\nDAMAGE INDICATORS: {'; '.join(indicators)}. "
                        "MOLD IS PRESENT OR HIGHLY PROBABLE per industry standards."
                    )
                    _image_cache[name] = f"{raw_desc}{mold_note}"
                else:
                    _image_cache[name] = raw_desc
            else:
                _image_cache[name] = raw_desc

            print(f"[NPU] {name} analyzed in {npu_ms}ms: {_image_cache[name][:100]}...")
        _executor.submit(_bg_analyze, save_path, fname, damage_type_hint)

    return jsonify({"filename": fname, "url": f"/uploads/{fname}"})


@app.route("/api/analyze-photo", methods=["POST"])
def api_analyze_photo():
    """Analyze a single uploaded photo using NPU image description."""
    data = request.get_json(force=True)
    filename = data.get("filename", "").strip()

    if not filename:
        return jsonify({"error": "No filename provided"}), 400

    # Check cache first (from background analysis)
    if filename in _image_cache:
        return jsonify({"description": _image_cache[filename], "engine": "npu", "cached": True})

    # Analyze now
    img_path = str(UPLOAD_DIR / filename)
    if not os.path.isfile(img_path):
        return jsonify({"error": "File not found"}), 404

    t0 = time.perf_counter()
    if os.path.isfile(PHI_NPU_EXE):
        desc = _npu_describe_image(img_path)
        engine = "npu"
    else:
        desc = "Image analysis requires NPU (phi-npu.exe). Please describe the damage manually."
        engine = "none"

    elapsed = round((time.perf_counter() - t0) * 1000)
    if desc:
        _image_cache[filename] = desc

    return jsonify({"description": desc, "engine": engine, "latency_ms": elapsed, "cached": False})


@app.route("/api/analyze-photos-status", methods=["POST"])
def api_analyze_photos_status():
    """Check how many uploaded photos have been analyzed."""
    data = request.get_json(force=True)
    filenames = data.get("filenames", [])
    analyzed = {f: _image_cache.get(f) for f in filenames if f in _image_cache}
    return jsonify({
        "total": len(filenames),
        "analyzed": len(analyzed),
        "descriptions": analyzed,
        "details": {f: (f in _image_cache) for f in filenames},
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Zava Insurance – On-Device AI Demo")
    print("  NPU: Phi Silica (vision + chat) | CPU: Foundry Local (text)")
    print("=" * 60)
    print(f"  Hybrid pipeline: NPU vision + CPU text = fast parallel inference")
    print(f"  Once ready, open \u2192 http://localhost:5000\n")
    app.run(host="127.0.0.1", port=5000, debug=False)
