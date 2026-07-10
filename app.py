"""
app.py — IBM InterviewTrainer Agent
Flask backend + IBM Watsonx.ai Granite + FAISS RAG
"""
from __future__ import annotations

import os
import re
import uuid
import logging
import warnings
from datetime import datetime, timezone

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    session,
    redirect,
    url_for,
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# ── Load environment variables from .env ─────────────────────────────────────
load_dotenv()

# ── Agent configuration (AGENT_INSTRUCTIONS) ─────────────────────────────────
from agent_config import (
    AGENT_INSTRUCTIONS,
    SYSTEM_PROMPT_TEMPLATE,
    QUESTION_GENERATION_PROMPT,
    FEEDBACK_PROMPT,
)

# ── RAG Engine ────────────────────────────────────────────────────────────────
from rag_engine import RAGEngine

# ── Logging Setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# Silence noisy third-party libraries
for _noisy in (
    "httpx", "httpcore", "huggingface_hub", "sentence_transformers",
    "transformers", "filelock", "urllib3", "lomond",
    "ibm_watsonx_ai", "ibm_watsonx_ai.wml_client_error",
):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

# werkzeug: keep INFO so "Running on http://…" prints, but drop SSL/Bad-request noise
_wz = logging.getLogger("werkzeug")
_wz.setLevel(logging.INFO)
_wz.addFilter(lambda r: "Bad request" not in r.getMessage())

# Suppress Python warnings from HuggingFace hub
warnings.filterwarnings("ignore")

# ═════════════════════════════════════════════════════════════════════════════
#  Flask App Initialization
# ═════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-fallback-change-in-prod")
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))

UPLOAD_FOLDER   = "uploads"
ALLOWED_EXTENSIONS = {"txt", "pdf", "docx", "md"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs("instance", exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ═════════════════════════════════════════════════════════════════════════════
#  IBM Watsonx.ai Client
# ═════════════════════════════════════════════════════════════════════════════

def _build_watsonx_client():
    """Initialise the IBM Watsonx.ai model. Returns None if credentials missing."""
    api_key    = os.getenv("IBM_API_KEY", "")
    project_id = os.getenv("IBM_PROJECT_ID", "")
    url        = os.getenv("IBM_WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
    model_id   = os.getenv("GRANITE_MODEL_ID", "ibm/granite-3-3-8b-instruct")

    _placeholders = {"", "your_ibm_cloud_api_key_here", "demo", "test"}
    if api_key in _placeholders or project_id in _placeholders:
        logger.warning("IBM_API_KEY not configured — running in DEMO mode.")
        return None

    try:
        from ibm_watsonx_ai import Credentials
        from ibm_watsonx_ai.foundation_models import ModelInference
        from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as Params

        credentials = Credentials(url=url, api_key=api_key)
        llm_params  = AGENT_INSTRUCTIONS["llm_params"]
        params = {
            Params.MAX_NEW_TOKENS:     llm_params["max_new_tokens"],
            Params.MIN_NEW_TOKENS:     llm_params["min_new_tokens"],
            Params.TEMPERATURE:        llm_params["temperature"],
            Params.TOP_P:              llm_params["top_p"],
            Params.TOP_K:              llm_params["top_k"],
            Params.REPETITION_PENALTY: llm_params["repetition_penalty"],
            Params.STOP_SEQUENCES:     llm_params["stop_sequences"],
        }
        model = ModelInference(
            model_id=model_id,
            credentials=credentials,
            project_id=project_id,
            params=params,
        )
        logger.info("Watsonx.ai model '%s' initialised successfully.", model_id)
        return model

    except Exception as exc:
        logger.error("Watsonx.ai init failed: %s", exc)
        return None


watsonx_model = _build_watsonx_client()

# ═════════════════════════════════════════════════════════════════════════════
#  RAG Engine Initialisation
# ═════════════════════════════════════════════════════════════════════════════

rag_engine = RAGEngine(
    kb_dir=AGENT_INSTRUCTIONS["knowledge_base_dir"],
    chunk_size=int(os.getenv("CHUNK_SIZE", 500)),
    chunk_overlap=int(os.getenv("CHUNK_OVERLAP", 50)),
    top_k=AGENT_INSTRUCTIONS["rag_top_k"],
    min_score=AGENT_INSTRUCTIONS["rag_min_score"],
)
logger.info("RAG engine ready: %d chunks indexed.", rag_engine.chunk_count)

# ═════════════════════════════════════════════════════════════════════════════
#  LLM Helper
# ═════════════════════════════════════════════════════════════════════════════

def call_llm(prompt: str, system_context: str = "") -> str:
    """Call Watsonx.ai Granite. Falls back to demo response when no credentials."""
    full_prompt = f"{system_context}\n\n{prompt}".strip() if system_context else prompt

    if watsonx_model:
        try:
            response = watsonx_model.generate_text(prompt=full_prompt)
            return response.strip() if response else "I couldn't generate a response. Please try again."
        except Exception as exc:
            logger.error("LLM call error: %s", exc)
            return _demo_response(prompt)
    return _demo_response(prompt)


# ── Demo question bank — 20 questions across all types ──────────────────────
_DEMO_QUESTIONS = [
    {
        "q": "Tell me about yourself.",
        "type": "Behavioral", "difficulty": "Beginner",
        "tip": "Use the **Present → Past → Future** formula. Keep it under 90 seconds and always tie it back to the role.",
        "framework": None,
        "model": "I'm a software engineer with 3 years of experience building scalable web applications. Previously I interned at a fintech startup where I improved API response time by 35%. I'm now looking to join a team where I can work on high-impact products and grow into a senior engineering role.",
        "interviewer_insight": "Interviewers want a **concise, role-relevant pitch** — not your life story. They're assessing communication clarity and self-awareness.",
    },
    {
        "q": "Describe a time you faced a major challenge at work and how you handled it.",
        "type": "Behavioral (STAR)", "difficulty": "Intermediate",
        "tip": "Use **STAR**: Situation → Task → Action → Result. Quantify your result — numbers make answers memorable.",
        "framework": "**S**ituation | **T**ask | **A**ction | **R**esult",
        "model": "Our production database crashed 2 hours before a major client demo (S). As the on-call engineer, I had to restore it without losing data (T). I rolled back to the last clean snapshot, patched the corrupted index, and ran integrity checks (A). We restored service in 47 minutes with zero data loss and the demo went ahead successfully (R).",
        "interviewer_insight": "Interviewers look for **ownership**, **calm under pressure**, and a **measurable outcome**. Avoid saying 'we' — use 'I'.",
    },
    {
        "q": "What is the difference between a process and a thread?",
        "type": "Technical", "difficulty": "Intermediate",
        "tip": "Start with the definition, give the key difference, then give a real-world example. Mention memory isolation.",
        "framework": None,
        "model": "A **process** is an independent program in execution with its own memory space. A **thread** is a lightweight unit of execution within a process that shares the same memory. Processes are isolated — a crash in one doesn't affect others. Threads share memory, making communication faster but requiring synchronisation (mutexes, semaphores) to avoid race conditions.",
        "interviewer_insight": "Interviewers want to see you understand **memory isolation** and **concurrency trade-offs**, not just a textbook definition.",
    },
    {
        "q": "Where do you see yourself in 5 years?",
        "type": "HR / Career", "difficulty": "Beginner",
        "tip": "Show ambition aligned with the company's growth path. Be specific but realistic. Demonstrate loyalty.",
        "framework": None,
        "model": "In 5 years I see myself as a senior engineer or tech lead, having shipped several high-impact features and mentored junior developers. I'm particularly excited about growing into system design and architecture, which aligns well with the direction of this team.",
        "interviewer_insight": "Interviewers are checking: Will this person stay? Are they ambitious but realistic? Does their goal align with what we can offer?",
    },
    {
        "q": "Explain the SOLID principles with an example.",
        "type": "Technical", "difficulty": "Advanced",
        "tip": "Name each principle, give a one-line definition, and use a concrete code example for at least 2 of them.",
        "framework": "**S**ingle Responsibility · **O**pen/Closed · **L**iskov Substitution · **I**nterface Segregation · **D**ependency Inversion",
        "model": "SOLID is a set of OOP design principles. **Single Responsibility**: a class should have one reason to change — e.g. separate `UserAuth` from `UserProfile`. **Open/Closed**: open for extension, closed for modification — use inheritance or interfaces instead of editing existing classes. These principles reduce coupling, increase testability, and make code easier to maintain.",
        "interviewer_insight": "Interviewers want **practical examples**, not just definitions. Bonus points for mentioning how violating these principles causes real bugs.",
    },
    {
        "q": "Tell me about a time you disagreed with your manager or teammate.",
        "type": "Behavioral (STAR)", "difficulty": "Intermediate",
        "tip": "Focus on **how** you resolved it, not the disagreement itself. Show empathy, data-driven reasoning, and professionalism.",
        "framework": "**S**ituation | **T**ask | **A**ction | **R**esult",
        "model": "My manager wanted to release a feature without unit tests due to deadline pressure (S). I was responsible for code quality (T). I prepared a 5-minute presentation showing the risk of regression bugs vs. 2 extra days for testing (A). We agreed on a middle ground — critical path tests only. The feature shipped on time with no production bugs (R).",
        "interviewer_insight": "They're testing your **conflict resolution** and **communication skills**. Never badmouth the other person — show mutual respect.",
    },
    {
        "q": "How would you design a URL shortener like bit.ly?",
        "type": "System Design", "difficulty": "Advanced",
        "tip": "Use the **RESHADED** framework: Requirements → Estimation → Storage → High-level design → APIs → Data model → Evaluation.",
        "framework": "Requirements → Scale Estimation → API Design → Database Schema → Caching → Trade-offs",
        "model": "**Requirements**: shorten URL, redirect, analytics, expiry. **Scale**: 100M URLs/day → ~1,200 writes/sec. **Encoding**: Base62 on MD5 hash, take first 7 chars. **DB**: NoSQL (Cassandra) for high write throughput. **Schema**: {short_code, long_url, created_at, expiry, clicks}. **Cache**: Redis for hot URLs. **CDN** for global redirect speed.",
        "interviewer_insight": "Interviewers look for **structured thinking**, **trade-off awareness** (SQL vs NoSQL, cache vs DB), and realistic scale estimates.",
    },
    {
        "q": "What are your greatest strengths?",
        "type": "HR / Behavioral", "difficulty": "Beginner",
        "tip": "Pick **2-3 strengths relevant to the role**. Back each one with a concrete example. Avoid generic answers like 'hardworking'.",
        "framework": "Strength → Evidence → Impact",
        "model": "My biggest strength is **problem decomposition** — I can break complex, ambiguous problems into clear, actionable steps. For example, when our team was stuck on a performance bottleneck, I broke it into profiling → identifying the hot path → benchmarking solutions, and we achieved a 60% latency reduction in a week.",
        "interviewer_insight": "They want **specific, role-relevant strengths with proof**, not personality traits. The example is what makes the answer believable.",
    },
    {
        "q": "What is your greatest weakness?",
        "type": "HR / Behavioral", "difficulty": "Beginner",
        "tip": "Pick a **genuine but non-critical** weakness. Show **self-awareness + active improvement steps**. Never say 'I work too hard'.",
        "framework": "Weakness → Why it matters → What you're doing to improve → Evidence of progress",
        "model": "I used to struggle with delegating tasks — I'd take on too much myself to ensure quality. I've been actively working on this by documenting clear acceptance criteria before delegating and doing structured check-ins instead of micromanaging. In my last sprint, I delegated 40% of my tasks and the team delivered on time.",
        "interviewer_insight": "They're assessing **self-awareness and growth mindset**. A candidate who can't name a weakness raises red flags.",
    },
    {
        "q": "Explain the difference between SQL and NoSQL databases. When would you use each?",
        "type": "Technical", "difficulty": "Intermediate",
        "tip": "Cover structure, ACID vs BASE, and give a concrete use-case for each. Mention CAP theorem for senior roles.",
        "framework": "Structure · Scalability · Consistency · Use-case",
        "model": "**SQL** (e.g. PostgreSQL): structured data, ACID transactions, strong consistency — ideal for banking, e-commerce orders. **NoSQL** (e.g. MongoDB, Cassandra): flexible schema, horizontal scaling, eventual consistency — ideal for social feeds, IoT data, real-time analytics. I'd choose SQL when data relationships are complex and consistency is critical; NoSQL when write throughput and scale matter more.",
        "interviewer_insight": "Interviewers want **trade-off awareness** — not just 'NoSQL scales better'. Show you understand when *not* to use NoSQL.",
    },
    {
        "q": "Describe a situation where you had to learn something new very quickly.",
        "type": "Behavioral (STAR)", "difficulty": "Intermediate",
        "tip": "Show your **learning process** — how you approached it, not just what you learned. Mention resources, timelines, and outcome.",
        "framework": "**S**ituation | **T**ask | **A**ction | **R**esult",
        "model": "We had to migrate our backend to Kubernetes in 3 weeks and I had no prior K8s experience (S/T). I dedicated 2 hours daily to the official docs and built a toy cluster in parallel (A). By week 2 I was deploying our staging environment and by week 3 production was live — 30% infrastructure cost reduction (R).",
        "interviewer_insight": "They're testing **learning agility** — a top predictor of job success. Show structured self-learning, not just 'I Googled it'.",
    },
    {
        "q": "How do you handle multiple high-priority tasks with the same deadline?",
        "type": "Situational", "difficulty": "Intermediate",
        "tip": "Show a **prioritisation framework** (RICE, MoSCoW, or Eisenhower Matrix). Mention stakeholder communication.",
        "framework": "Clarify → Prioritise → Communicate → Execute → Review",
        "model": "First I clarify actual urgency with stakeholders — deadlines often have flexibility. Then I use impact vs effort to rank tasks. I timebox each task and communicate realistic ETAs upfront. If truly blocked, I escalate early rather than silently missing deadlines. I also batch similar tasks to reduce context-switching overhead.",
        "interviewer_insight": "Interviewers want to see **structured thinking + proactive communication**, not just 'I work harder'. Disorganised candidates panic — great ones triage.",
    },
    {
        "q": "What is a closure in JavaScript / Python?",
        "type": "Technical", "difficulty": "Intermediate",
        "tip": "Define it, explain *why* it exists, and give a short code example. Connect it to a practical use-case like memoization or callbacks.",
        "framework": None,
        "model": "A **closure** is a function that remembers the variables from its enclosing scope even after that scope has finished executing. In Python: `def make_counter(): count=0; def inc(): nonlocal count; count+=1; return count; return inc` — calling `inc()` repeatedly increments `count` without it being a global. Closures are used for data encapsulation, factory functions, and decorators.",
        "interviewer_insight": "They want to see you explain **scope and memory** clearly — not just the definition. Bonus: mention how closures can cause memory leaks if misused.",
    },
    {
        "q": "Why do you want to work at this company?",
        "type": "HR / Motivation", "difficulty": "Beginner",
        "tip": "Research the company **before** the interview. Mention specific products, culture values, or recent milestones. Be genuine.",
        "framework": "What excites you → Why you're a fit → What you'll contribute",
        "model": "I've been following your product for 2 years — the way you've built a developer-first API platform is exactly the kind of technical product I want to work on. Your engineering blog posts about distributed systems align with what I'm passionate about. I want to contribute my backend experience to your infrastructure team and grow alongside a company that values technical depth.",
        "interviewer_insight": "Generic answers ('great company', 'good culture') are red flags. Specific answers show **genuine interest and preparation**.",
    },
    {
        "q": "Explain how you would approach debugging a production issue.",
        "type": "Technical / Situational", "difficulty": "Intermediate",
        "tip": "Walk through a **systematic process** — don't jump to solutions. Show calm, methodical thinking.",
        "framework": "Detect → Assess Impact → Isolate → Fix → Verify → Post-mortem",
        "model": "1. **Check monitoring** — dashboards, error rates, latency spikes. 2. **Assess blast radius** — how many users affected? 3. **Reproduce** in staging if possible. 4. **Isolate** — recent deployments, config changes, external dependencies. 5. **Fix or rollback** — hotfix if quick, rollback if uncertain. 6. **Verify** — confirm metrics normalise. 7. **Write a post-mortem** — root cause, timeline, prevention steps.",
        "interviewer_insight": "They want **systematic thinking under pressure**. Mentioning post-mortems shows engineering maturity.",
    },
    {
        "q": "Tell me about a project you're most proud of.",
        "type": "Behavioral", "difficulty": "Beginner",
        "tip": "Pick a project where **you had significant impact**. Cover the problem, your role, tech used, and measurable outcome.",
        "framework": "Problem → Your Role → Approach → Outcome → What you learned",
        "model": "I built an automated invoice reconciliation system that replaced a 4-hour weekly manual process. I designed the ETL pipeline in Python, integrated with our ERP via REST APIs, and added anomaly detection using statistical thresholds. It reduced reconciliation time by 95% and caught 3 billing errors in the first month that would have cost $12K.",
        "interviewer_insight": "Interviewers love **quantified impact + ownership**. 'We built' is weak — 'I designed and shipped' is strong.",
    },
    {
        "q": "How do you ensure code quality in your projects?",
        "type": "Technical / Process", "difficulty": "Intermediate",
        "tip": "Cover the full quality spectrum: testing, code review, linting, CI/CD, documentation. Show you think beyond just 'writing tests'.",
        "framework": "Write → Review → Test → Automate → Monitor",
        "model": "I follow a multi-layered approach: **unit tests** for business logic, **integration tests** for API contracts, **linting** (ESLint/flake8) enforced in CI. I write self-documenting code with clear naming and add docstrings for public APIs. Every PR goes through code review with at least one approval. I also track code coverage and fail the build below 80%.",
        "interviewer_insight": "Senior candidates mention **preventing defects upstream** (design, review) not just catching them in tests.",
    },
    {
        "q": "Describe your experience with Agile or Scrum.",
        "type": "Process / Behavioral", "difficulty": "Beginner",
        "tip": "Don't just list ceremonies. Show how Agile **helped your team deliver better outcomes** and how you contributed.",
        "framework": "Ceremonies → Your Role → Value Delivered",
        "model": "I've worked in 2-week sprints with daily standups, sprint planning, retrospectives, and demos. As the sprint lead in my last role, I facilitated retrospectives and introduced a 'blocked items' board which reduced task blockers by 60%. I believe Agile works best when the team genuinely uses retrospectives to improve, not just as a checkbox.",
        "interviewer_insight": "They want to see you **understand the value**, not just the process. Mention a concrete improvement you drove.",
    },
    {
        "q": "How do you handle receiving critical feedback?",
        "type": "Behavioral / HR", "difficulty": "Beginner",
        "tip": "Show **receptiveness, reflection, and action**. Give a real example of feedback you received and what you changed.",
        "framework": "Receive openly → Reflect → Act → Follow up",
        "model": "I genuinely welcome critical feedback — it's the fastest way to grow. In my last performance review, my manager noted that my written communication in tickets was too terse, causing confusion. I started adding 'context' and 'acceptance criteria' sections to every ticket. Three months later my manager specifically called out the improvement in my next review.",
        "interviewer_insight": "Red flag: defensive answers. Green flag: **specific example + measurable change**. They're assessing coachability.",
    },
    {
        "q": "What is your approach to estimating development tasks?",
        "type": "Technical / Process", "difficulty": "Intermediate",
        "tip": "Mention **decomposition, uncertainty buffers, and past data**. Show you communicate estimates honestly rather than overpromising.",
        "framework": "Decompose → Estimate each part → Add buffer → Communicate uncertainty",
        "model": "I break tasks into sub-tasks of 2-4 hours each — anything larger gets decomposed further. I use past velocity as a baseline and add a 20-30% buffer for unknowns. I explicitly flag estimates as rough (±50%) or confident (±20%) when communicating them. If scope changes mid-sprint I re-estimate and flag it immediately rather than silently slipping the deadline.",
        "interviewer_insight": "Interviewers want **honest, structured estimators** — not people who say 'sure, 2 days' for everything. Mentioning uncertainty shows engineering maturity.",
    },
]

# ── Demo feedback bank — 6 varied feedback responses ─────────────────────────
_DEMO_FEEDBACKS = [
    {
        "score": 4,
        "rating": "Strong",
        "worked": ["Clear Situation and Task provided ✓", "Good use of specific numbers ✓", "Confident, direct language ✓"],
        "improve": ["Action section could be more specific — *what exactly did YOU decide?*", "Add a follow-up result — what was the long-term impact?"],
        "insight": "Interviewers are mentally scoring ownership, specificity, and communication. You scored well on all three — just push the Action deeper.",
        "tip": "Record yourself answering out loud. Most people are surprised how much filler language ('like', 'um', 'basically') they use.",
    },
    {
        "score": 3,
        "rating": "Adequate",
        "worked": ["Good opening context ✓", "Showed awareness of the problem ✓"],
        "improve": ["Missing the **Result** entirely — what was the outcome?", "Action was vague — list 2-3 concrete steps you took", "Add a metric: %, $, time, or users impacted"],
        "insight": "A 3/5 answer tells the interviewer *what happened* but not *why it matters*. The Result is where you prove your value.",
        "tip": "Always end your STAR answer with: *'As a result, we achieved X, which meant Y for the business.'*",
    },
    {
        "score": 5,
        "rating": "Exceptional",
        "worked": ["Perfect STAR structure ✓", "Quantified result with real numbers ✓", "Showed leadership and initiative ✓", "Concise and within 2 minutes ✓"],
        "improve": ["Minor: briefly mention what you'd do differently — shows reflection"],
        "insight": "This answer would impress most interviewers. The quantified result and clear ownership are exactly what hiring managers look for.",
        "tip": "Now try delivering this answer in under 90 seconds — brevity at this quality level is rare and very impressive.",
    },
    {
        "score": 2,
        "rating": "Needs Work",
        "worked": ["You identified the core topic ✓"],
        "improve": ["No clear structure — use STAR (Situation → Task → Action → Result)", "Too generic — interviewers hear 'I'm a team player' 50 times a day. Give a *specific* example", "No numbers or measurable outcome mentioned", "Answer was too brief — aim for 90-120 seconds"],
        "insight": "The interviewer can't assess you on vague answers. Specificity is everything — every claim needs a supporting example.",
        "tip": "Prepare 5 core STAR stories that cover: leadership, conflict, failure, success under pressure, and cross-team collaboration. Map them to any question.",
    },
    {
        "score": 4,
        "rating": "Strong",
        "worked": ["Excellent technical depth ✓", "Explained trade-offs clearly ✓", "Used a real-world example ✓"],
        "improve": ["Could mention edge cases or failure modes", "Briefly acknowledge alternative approaches and why you ruled them out"],
        "insight": "Senior interviewers specifically look for **trade-off awareness** — you demonstrated this well. Mentioning what you *didn't* do and why separates strong engineers from great ones.",
        "tip": "For every technical decision in your answer, add: *'We chose X over Y because Z'* — this shows engineering maturity.",
    },
    {
        "score": 3,
        "rating": "Adequate",
        "worked": ["Showed knowledge of the concept ✓", "Gave a relevant example ✓"],
        "improve": ["Connect the concept to a **business outcome** — why does it matter?", "Mention limitations or when *not* to use this approach", "Use more precise technical terminology"],
        "insight": "You know the *what* — now show the interviewer you know the *why* and *when*. That's the difference between a 3 and a 5.",
        "tip": "After every technical answer, ask yourself: *'Could a non-technical manager understand why this matters?'* If yes, your answer is complete.",
    },
]


def _demo_response(prompt: str) -> str:
    """
    Dynamic demo mode — rotates through 20 questions, provides rich structured
    feedback, and adapts to role/experience from the prompt context.
    """
    import hashlib
    p = prompt.lower()

    # ── Detect what kind of response is needed ────────────────────────────────
    is_intro    = any(w in p for w in ("candidate has introduced", "has introduced themselves"))
    is_feedback = any(w in p for w in ("evaluate this interview", "candidate answer", "user_answer"))
    is_hint     = any(w in p for w in ("hint for answering", "give a hint"))
    is_summary  = any(w in p for w in ("session summary", "motivating session"))

    # ── Pick question — use hash of prompt for variety, not always the same ──
    q_index = int(hashlib.md5(prompt[:80].encode()).hexdigest(), 16) % len(_DEMO_QUESTIONS)
    q_data  = _DEMO_QUESTIONS[q_index]

    # ── Detect role from prompt ───────────────────────────────────────────────
    role = "your target role"
    for kw in ("software engineer", "data analyst", "product manager", "marketing",
               "sales", "finance", "hr", "devops", "frontend", "backend", "designer"):
        if kw in p:
            role = kw.title()
            break

    # ── INTRO: welcome + first question ──────────────────────────────────────
    if is_intro:
        first_q = _DEMO_QUESTIONS[0]  # Always start with "Tell me about yourself"
        return (
            f"## 👋 Welcome! Let's get started.\n\n"
            f"Great to meet you! I've tailored your session for **{role}**. "
            f"I'll ask you **5 questions** — a mix of behavioral, technical, and HR — "
            f"then give you detailed feedback after each answer.\n\n"
            f"---\n\n"
            f"## 📋 Question 1 of 5\n\n"
            f"### {first_q['q']}\n\n"
            f"**Type:** {first_q['type']} &nbsp;|&nbsp; **Difficulty:** {first_q['difficulty']}\n\n"
            f"---\n\n"
            f"💡 **How to answer:** {first_q['tip']}\n\n"
            + (f"> 📐 **Framework:** {first_q['framework']}\n\n" if first_q['framework'] else "")
            + f"⏱️ *Take your time — aim for a 90-second answer. Type it below when ready!*"
        )

    # ── FEEDBACK: rich structured analysis ───────────────────────────────────
    if is_feedback:
        fb_index = int(hashlib.md5(prompt[50:130].encode()).hexdigest(), 16) % len(_DEMO_FEEDBACKS)
        fb = _DEMO_FEEDBACKS[fb_index]
        score_label = {5:"🟢 Exceptional", 4:"🔵 Strong", 3:"🟡 Adequate", 2:"🟠 Needs Work", 1:"🔴 Incomplete"}
        worked  = "\n".join(f"- {w}" for w in fb["worked"])
        improve = "\n".join(f"- {w}" for w in fb["improve"])
        return (
            f"## 💬 Answer Analysis\n\n"
            f"---\n\n"
            f"### ✅ What You Did Well\n{worked}\n\n"
            f"### ⚠️ Areas to Strengthen\n{improve}\n\n"
            f"---\n\n"
            f"### 📖 Model Answer Framework\n\n"
            f"*{q_data['model']}*\n\n"
            f"---\n\n"
            f"### 💡 Interviewer Insight\n\n"
            f"{fb['insight']}\n\n"
            f"---\n\n"
            f"### 🎯 Pro Tip\n\n"
            f"{fb['tip']}\n\n"
            f"---\n\n"
            f"## ⭐ Score: **{fb['score']} / 5** — {score_label[fb['score']]}\n\n"
        )

    # ── HINT ─────────────────────────────────────────────────────────────────
    if is_hint:
        return (
            f"## 💡 Hint\n\n"
            f"Here's how to approach this without giving away the full answer:\n\n"
            f"**Structure to use:** {q_data['framework'] or 'Direct Answer → Example → Impact'}\n\n"
            f"**Key things to cover:**\n"
            f"- Start by briefly setting the context (1-2 sentences)\n"
            f"- Focus on YOUR specific actions, not the team's\n"
            f"- End with a measurable outcome\n\n"
            f"**What interviewers look for:** {q_data['interviewer_insight']}\n\n"
            f"> ⏱️ Don't overthink it — type your best answer and I'll give you detailed feedback!"
        )

    # ── SUMMARY ──────────────────────────────────────────────────────────────
    if is_summary:
        return (
            f"## 🏁 Session Complete — Great Work!\n\n"
            f"---\n\n"
            f"### 📊 Session Summary\n\n"
            f"You've completed a full interview practice session. Here's your assessment:\n\n"
            f"**Overall:** You showed solid preparation and willingness to engage deeply with each question. "
            f"The quality of your answers improved noticeably as the session progressed.\n\n"
            f"---\n\n"
            f"### 💪 Top Strengths\n"
            f"- Strong communication and ability to structure answers\n"
            f"- Good use of specific examples from real experience\n"
            f"- Demonstrated self-awareness and growth mindset\n\n"
            f"### 🎯 Top 3 Areas to Improve\n"
            f"1. **Quantify results** — add numbers, percentages, or timelines to every answer\n"
            f"2. **Deepen technical answers** — go beyond definitions to trade-offs and real-world application\n"
            f"3. **Practice conciseness** — aim for 90-second answers; trim filler words\n\n"
            f"---\n\n"
            f"### 🚀 Next Steps\n"
            f"1. Add your real **IBM API key** to `.env` for live AI-powered feedback\n"
            f"2. Upload role-specific documents to the **Knowledge Base** for tailored questions\n"
            f"3. Try **Mock Interview Mode** (⏱ button) for timed pressure practice\n"
            f"4. Click **New Session** to practice a different role or question type\n\n"
            f"---\n\n"
            f"*Keep practicing — confidence comes from repetition! 🎯*"
        )

    # ── NEXT QUESTION (default) ───────────────────────────────────────────────
    q = q_data
    return (
        f"## 📋 Next Question\n\n"
        f"### {q['q']}\n\n"
        f"**Type:** {q['type']} &nbsp;|&nbsp; **Difficulty:** {q['difficulty']}\n\n"
        f"---\n\n"
        f"💡 **Tip:** {q['tip']}\n\n"
        + (f"> 📐 **Framework:** {q['framework']}\n\n" if q['framework'] else "")
        + f"---\n\n"
        f"🎯 **What interviewers look for:** {q['interviewer_insight']}\n\n"
        f"⏱️ *Type your answer below — I'll give you a full breakdown with score, model answer, and tips!*"
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Session Helpers
# ═════════════════════════════════════════════════════════════════════════════

def get_session_data() -> dict:
    if "interview_data" not in session:
        session["interview_data"] = {
            "session_id":       str(uuid.uuid4())[:8],
            "started_at":       datetime.now(timezone.utc).isoformat(),
            "experience_level": None,
            "years_experience": None,
            "target_role":      None,
            "questions_asked":  0,
            "scores":           [],
            "history":          [],
            "phase":            "intro",
            "current_question": None,
            "question_types":   {"technical": 0, "behavioral": 0, "situational": 0},
        }
    return session["interview_data"]


def save_session_data(data: dict) -> None:
    session["interview_data"] = data
    session.modified = True


def build_system_prompt(data: dict, rag_context: str = "") -> str:
    cfg   = AGENT_INSTRUCTIONS
    exp   = data.get("experience_level", "Not specified")
    years = data.get("years_experience", "")
    exp_label = f"{exp} ({years} years)" if years else exp

    difficulty = "intermediate"
    difficulty_map = cfg["difficulty_levels"]
    if exp == "fresher":
        difficulty = difficulty_map.get("fresher", "beginner")
    elif years:
        try:
            yrs = int(years)
        except (ValueError, TypeError):
            yrs = 0
        for key, val in difficulty_map.items():
            # strip any text like " years", spaces — keep only digits and "-"/"+"
            key_str = re.sub(r"[^\d\-\+]", "", str(key))
            if "-" in key_str:
                parts = key_str.split("-")
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    if int(parts[0]) <= yrs <= int(parts[1]):
                        difficulty = val
                        break
            elif "+" in key_str:
                base = key_str.replace("+", "")
                if base.isdigit() and yrs >= int(base):
                    difficulty = val

    return SYSTEM_PROMPT_TEMPLATE.format(
        agent_name=cfg["agent_name"],
        tone=cfg["tone"],
        experience_level=exp_label,
        target_role=data.get("target_role", "General"),
        current_q=data.get("questions_asked", 0) + 1,
        total_q=cfg["questions_per_session"],
        rag_context=rag_context or "No specific context retrieved.",
        difficulty=difficulty,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Routes — Pages
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/chat", methods=["GET"])
def chat():
    data = get_session_data()
    save_session_data(data)
    return render_template("chat.html", agent_name=AGENT_INSTRUCTIONS["agent_name"])


@app.route("/dashboard", methods=["GET"])
def dashboard():
    data = get_session_data()
    return render_template("dashboard.html", session_data=data)


@app.route("/reset", methods=["GET"])
def reset_session():
    session.clear()
    return redirect(url_for("index"))


# ═════════════════════════════════════════════════════════════════════════════
#  Routes — API
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/api/start", methods=["POST"])
def api_start():
    """Initialize session and return greeting message."""
    session.clear()
    data = get_session_data()

    greeting = AGENT_INSTRUCTIONS["greeting_message"]
    data["history"].append({
        "role":      "assistant",
        "content":   greeting,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    save_session_data(data)

    return jsonify({
        "status":     "ok",
        "message":    greeting,
        "session_id": data["session_id"],
    })


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Main chat endpoint — process user message and return AI response."""
    body         = request.get_json(force=True) or {}
    user_message = (body.get("message") or "").strip()

    if not user_message:
        return jsonify({"status": "error", "message": "Empty message."}), 400

    data = get_session_data()
    cfg  = AGENT_INSTRUCTIONS

    data["history"].append({
        "role":      "user",
        "content":   user_message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    if data["phase"] == "intro":
        response_text = _handle_intro(user_message, data)
    else:
        response_text = _handle_question_phase(user_message, data)

    if data["questions_asked"] >= cfg["max_session_questions"]:
        data["phase"] = "summary"
        if cfg["auto_generate_summary"]:
            response_text += "\n\n" + _generate_summary(data)

    data["history"].append({
        "role":      "assistant",
        "content":   response_text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    save_session_data(data)

    scores = data["scores"]
    return jsonify({
        "status":  "ok",
        "message": response_text,
        "phase":   data["phase"],
        "progress": {
            "questions_asked": data["questions_asked"],
            "total":           cfg["questions_per_session"],
            "scores":          scores,
            "avg_score":       round(sum(scores) / len(scores), 1) if scores else 0,
        },
    })


# ── Private helpers ───────────────────────────────────────────────────────────

def _handle_intro(user_message: str, data: dict) -> str:
    """Parse user profile from first message and start question phase."""
    msg_lower = user_message.lower()

    if any(w in msg_lower for w in ("fresher", "fresh", "entry", "graduate")):
        data["experience_level"] = "fresher"
        data["years_experience"] = 0
    else:
        data["experience_level"] = "experienced"
        match = re.search(r"(\d+)\s*(?:year|yr)", msg_lower)
        data["years_experience"] = int(match.group(1)) if match else 3

    role_keywords = [
        "software", "engineer", "developer", "manager", "analyst", "designer",
        "marketing", "sales", "finance", "data", "product", "hr", "devops",
        "cloud", "frontend", "backend", "fullstack", "machine learning", "ai",
        "consultant", "operations", "research", "scientist",
    ]
    found_role = "General Professional"
    for kw in role_keywords:
        if kw in msg_lower:
            words = user_message.split()
            for i, w in enumerate(words):
                if kw in w.lower():
                    chunk = words[max(0, i - 1): min(len(words), i + 3)]
                    found_role = " ".join(chunk).strip(".,!?")
                    break
            break

    data["target_role"] = found_role
    data["phase"]       = "questions"

    query   = f"interview questions {found_role} {data['experience_level']}"
    rag_ctx = rag_engine.retrieve(query) if AGENT_INSTRUCTIONS["rag_enabled"] else ""
    system  = build_system_prompt(data, rag_ctx)
    prompt  = (
        f"The candidate introduced themselves as: \"{user_message}\".\n\n"
        f"Acknowledge their profile warmly, then ask the FIRST interview question "
        f"for a {data['experience_level']} targeting {found_role}. "
        f"Format it clearly with type and difficulty tags."
    )
    data["questions_asked"] += 1
    data["question_types"]["behavioral"] += 1
    return call_llm(prompt, system)


def _handle_question_phase(user_message: str, data: dict) -> str:
    """Evaluate the user's answer or handle navigation commands."""
    cfg       = AGENT_INSTRUCTIONS
    msg_lower = user_message.lower().strip()

    if msg_lower in ("next", "next question", "skip", "continue"):
        return _generate_next_question(data)
    if msg_lower in ("hint", "help", "tips"):
        return _give_hint(data)
    if msg_lower in ("summary", "result", "score", "results"):
        return _generate_summary(data)

    query   = f"feedback interview answer {data.get('target_role', '')} {user_message[:200]}"
    rag_ctx = rag_engine.retrieve(query) if cfg["rag_enabled"] else ""
    system  = build_system_prompt(data, rag_ctx)
    prompt  = FEEDBACK_PROMPT.format(
        question=data.get("current_question", "the previous question"),
        user_answer=user_message,
        experience_level=data.get("experience_level", "professional"),
        target_role=data.get("target_role", "the role"),
        rag_context=rag_ctx or "No specific context retrieved.",
    )

    feedback    = call_llm(prompt, system)
    score_match = re.search(r"[Ss]core[:\s]*\*{0,2}(\d)[^\d]", feedback)
    if score_match:
        score = min(max(int(score_match.group(1)), 1), 5)
        data["scores"].append(score)

    next_q = _generate_next_question(data)
    return feedback + "\n\n---\n\n" + next_q


def _generate_next_question(data: dict) -> str:
    cfg = AGENT_INSTRUCTIONS
    if data["questions_asked"] >= cfg["questions_per_session"]:
        data["phase"] = "summary"
        return _generate_summary(data)

    query   = f"interview questions {data.get('target_role', '')} {data.get('experience_level', '')}"
    rag_ctx = rag_engine.retrieve(query) if cfg["rag_enabled"] else ""
    system  = build_system_prompt(data, rag_ctx)

    q_num = data["questions_asked"] + 1
    if q_num % 3 == 0:
        q_type = "behavioral/STAR"
        data["question_types"]["behavioral"] += 1
    elif q_num % 3 == 1:
        q_type = "technical"
        data["question_types"]["technical"] += 1
    else:
        q_type = "situational"
        data["question_types"]["situational"] += 1

    prompt = (
        f"Generate interview question #{q_num} of {cfg['questions_per_session']} "
        f"for a {data.get('experience_level', 'professional')} targeting {data.get('target_role', 'the role')}.\n"
        f"Question type: {q_type}\n"
        f"Keep it focused and specific. Format with type and difficulty tags."
    )
    data["questions_asked"] += 1
    question = call_llm(prompt, system)
    data["current_question"] = question
    return question


def _give_hint(data: dict) -> str:
    q       = data.get("current_question", "")
    rag_ctx = rag_engine.retrieve(q) if AGENT_INSTRUCTIONS["rag_enabled"] else ""
    system  = build_system_prompt(data, rag_ctx)
    prompt  = f"Give a hint for answering this interview question without revealing the full answer:\n\n{q}"
    return call_llm(prompt, system)


def _generate_summary(data: dict) -> str:
    scores = data.get("scores", [])
    avg    = round(sum(scores) / len(scores), 1) if scores else 0
    qt     = data.get("question_types", {})

    summary_prompt = (
        f"Generate a motivating session summary for an interview practice session.\n\n"
        f"Candidate: {data.get('experience_level', 'professional')} targeting "
        f"{data.get('target_role', 'the role')}\n"
        f"Questions answered: {data.get('questions_asked', 0)}\n"
        f"Scores: {scores}\n"
        f"Average score: {avg}/5\n"
        f"Breakdown — Technical: {qt.get('technical', 0)}, "
        f"Behavioral: {qt.get('behavioral', 0)}, Situational: {qt.get('situational', 0)}\n\n"
        f"Include: overall assessment, top strengths, top 3 improvement areas, next steps."
    )
    rag_ctx = rag_engine.retrieve("interview preparation tips next steps improvement")
    system  = build_system_prompt(data, rag_ctx)
    return call_llm(summary_prompt, system)


# ═════════════════════════════════════════════════════════════════════════════
#  Routes — Upload
# ═════════════════════════════════════════════════════════════════════════════

def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file part."}), 400
    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"status": "error", "message": "No selected file."}), 400
    if not _allowed_file(file.filename):
        return jsonify({"status": "error", "message": "File type not allowed."}), 400

    filename = secure_filename(file.filename)
    dest     = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(dest)

    chunks_added = rag_engine.add_document(dest)
    return jsonify({
        "status":       "ok",
        "message":      f"Uploaded '{filename}' and indexed {chunks_added} chunks.",
        "chunks_added": chunks_added,
        "total_chunks": rag_engine.chunk_count,
    })


# ═════════════════════════════════════════════════════════════════════════════
#  Routes — Status / Health
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({
        "status":       "ok",
        "model":        os.getenv("GRANITE_MODEL_ID", "ibm/granite-3-3-8b-instruct"),
        "rag_ready":    rag_engine.is_ready,
        "rag_chunks":   rag_engine.chunk_count,
        "watsonx_live": watsonx_model is not None,
        "demo_mode":    watsonx_model is None,
        "agent_name":   AGENT_INSTRUCTIONS["agent_name"],
    })


@app.route("/api/session", methods=["GET"])
def api_session():
    data   = get_session_data()
    scores = data.get("scores", [])
    return jsonify({
        "session_id":       data.get("session_id"),
        "experience_level": data.get("experience_level"),
        "target_role":      data.get("target_role"),
        "questions_asked":  data.get("questions_asked", 0),
        "avg_score":        round(sum(scores) / len(scores), 1) if scores else 0,
        "scores":           scores,
        "phase":            data.get("phase"),
        "question_types":   data.get("question_types", {}),
    })


# ═════════════════════════════════════════════════════════════════════════════
#  Error Handlers
# ═════════════════════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(e):
    logger.error("500 error: %s", e)
    return jsonify({"status": "error", "message": "Internal server error."}), 500


# ═════════════════════════════════════════════════════════════════════════════
#  Entrypoint
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port    = int(os.getenv("PORT", 8081))
    debug   = os.getenv("FLASK_DEBUG", "True").lower() == "true"
    logger.info("Starting InterviewTrainer Agent on port %d (debug=%s)", port, debug)
    # use_reloader=False prevents the app loading twice (double model load)
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
