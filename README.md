# IBM InterviewTrainer Agent 🤖

> AI-powered interview coaching powered by **IBM Watsonx.ai Granite** models with **RAG** (Retrieval-Augmented Generation), FAISS vector search, and a modern dark-mode web UI.

---

## ✨ Features

| Feature | Details |
|---|---|
| **Personalized Questions** | Adapts to fresher / experienced levels and target role |
| **Technical + Behavioral** | STAR method, system design, coding concepts, HR questions |
| **RAG-Enhanced Responses** | FAISS vector index over knowledge base — not just LLM guesswork |
| **Instant Feedback** | Answer analysis, model answer, interviewer tips, 1–5 score |
| **Progress Dashboard** | Score charts, question type breakdown, readiness gauge |
| **Mock Interview Mode** | 2-minute countdown timer per question |
| **Knowledge Base Upload** | Upload TXT/PDF/DOCX files to extend the RAG knowledge base |
| **AGENT_INSTRUCTIONS** | Single config file to tune agent behavior, tone, difficulty |
| **Dark / Light Mode** | Full theme toggle with persistent preference |
| **Mobile Responsive** | Bootstrap 5.3, works on all screen sizes |

---

## 🏗️ Project Structure

```
InterviewTrainer Agent/
├── app.py                          # Flask app + Watsonx.ai integration
├── agent_config.py                 # ⭐ AGENT_INSTRUCTIONS — customize here!
├── rag_engine.py                   # FAISS RAG retrieval engine
├── requirements.txt
├── .env.example                    # Copy to .env with your credentials
│
├── knowledge_base/                 # RAG knowledge documents
│   ├── role_specific_questions.txt
│   ├── behavioral_hr_questions.txt
│   ├── technical_software_engineering.txt
│   └── interview_tips_guidelines.txt
│
├── uploads/                        # Runtime user uploads (gitignored)
├── instance/                       # FAISS index cache (gitignored)
│
├── templates/
│   ├── base.html                   # Layout with navbar + footer
│   ├── index.html                  # Landing page
│   ├── chat.html                   # Chat interface
│   ├── dashboard.html              # Progress dashboard
│   └── 404.html
│
└── static/
    ├── css/style.css               # All styles (dark mode, animations)
    └── js/
        ├── app.js                  # Global (theme toggle, upload)
        ├── chat.js                 # Chat UI + timer + session
        ├── dashboard.js            # Charts + progress analytics
        └── landing.js              # Landing page animations
```

---

## 🚀 Quick Start

### 1. Clone / Download
```bash
git clone <your-repo-url>
cd "InterviewTrainer Agent"
```

### 2. Create Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

> **Note:** `faiss-cpu` and `sentence-transformers` are optional but strongly recommended for full RAG functionality. If they aren't installed, the app falls back to keyword search.

### 4. Configure Environment Variables
```bash
cp .env.example .env
```

Edit `.env`:
```env
IBM_API_KEY=your_ibm_cloud_api_key_here
IBM_PROJECT_ID=your_watsonx_project_id_here
IBM_WATSONX_URL=https://us-south.ml.cloud.ibm.com
GRANITE_MODEL_ID=ibm/granite-3-3-8b-instruct
FLASK_SECRET_KEY=your-random-secret-key
```

### 5. Run the App
```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

---

## 🔑 Getting IBM Watsonx.ai Credentials

1. Sign up / log in at [IBM Cloud](https://cloud.ibm.com)
2. Create a **Watson Studio** project
3. Navigate to **Manage → Access (IAM)** → Create an API Key
4. Go to your Watson Studio project → **Manage → General** → copy the **Project ID**
5. Paste both into your `.env` file

**Without credentials:** The app runs in **Demo Mode** with realistic pre-built responses so you can fully test the UI.

---

## ⚙️ Customizing the Agent — `agent_config.py`

The `AGENT_INSTRUCTIONS` dictionary in [`agent_config.py`](agent_config.py) is your control center:

```python
AGENT_INSTRUCTIONS = {
    "agent_name":       "Alex",           # Name shown in UI
    "tone":             "professional_friendly",  # formal | casual | motivational
    "questions_per_session": 5,           # Batch size
    "difficulty_levels": {
        "fresher":    "beginner",
        "2-5 years":  "intermediate",
        "5-10 years": "advanced",
    },
    "question_distribution": {
        "technical":      40,   # % mix
        "behavioral_star":35,
        "situational":    15,
        "company_culture":10,
    },
    "feedback_verbosity": "detailed",     # brief | detailed | coaching
    "score_answers":      True,           # 1–5 scoring
    "rag_enabled":        True,           # Toggle RAG
    "rag_top_k":          5,              # Chunks retrieved per query
    "llm_params": {
        "temperature": 0.7,              # 0=deterministic, 1=creative
        "max_new_tokens": 1024,
    },
    # ... and much more
}
```

Edit any value and restart the server — no code changes needed.

---

## 📚 Expanding the Knowledge Base

### Add Files to `knowledge_base/`
Drop any `.txt`, `.pdf`, `.docx`, or `.md` file into the `knowledge_base/` directory and restart the app. The RAG engine auto-indexes all files at startup.

### Upload via UI
Use the upload button (📎) in the chat interface or the upload card on the landing page to add documents at runtime. They're indexed instantly.

---

## 💬 Chat Commands

| Command | Effect |
|---|---|
| `next` | Skip to next question |
| `hint` | Get a hint for the current question |
| `summary` | Generate session summary with scores |
| Type your answer | Receive structured feedback + next question |

---

## 🐳 Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "app:app"]
```

```bash
docker build -t interview-trainer .
docker run -p 5000:5000 --env-file .env interview-trainer
```

---

## ☁️ IBM Code Engine / Cloud Foundry Deployment

### IBM Code Engine
```bash
ibmcloud ce application create \
  --name interview-trainer \
  --image <your-registry>/interview-trainer:latest \
  --env-from-secret interview-trainer-secrets \
  --port 5000
```

### Environment Secrets
```bash
ibmcloud ce secret create --name interview-trainer-secrets \
  --from-literal IBM_API_KEY=your_key \
  --from-literal IBM_PROJECT_ID=your_project_id \
  --from-literal FLASK_SECRET_KEY=your_secret
```

---

## 🔒 Security

- **Never commit `.env`** — it's in `.gitignore`
- `FLASK_SECRET_KEY` must be a long random string in production
- Set `FLASK_DEBUG=False` and `FLASK_ENV=production` for production
- Consider adding authentication (Flask-Login) for production use
- The `uploads/` folder is served only via server-side processing, not publicly

---

## 🧪 Testing Without IBM Credentials

The app ships with a **Demo Mode** that fires when no valid API key is configured. You get realistic, structured responses covering:
- Profile intake (fresher/experienced + role)
- Question generation with type/difficulty tags  
- Structured feedback with STAR analysis, model answers, and scores
- Session summary

This lets you fully test the UI and frontend without spending IBM credits.

---

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `flask` | Web framework |
| `flask-session` | Server-side sessions |
| `python-dotenv` | `.env` loading |
| `ibm-watsonx-ai` | Granite LLM API |
| `sentence-transformers` | Text embeddings for RAG |
| `faiss-cpu` | Vector similarity search |
| `numpy` | Numerical operations |
| `PyPDF2` | PDF parsing for knowledge base |
| `python-docx` | DOCX parsing for knowledge base |
| `gunicorn` | Production WSGI server |

---

## 🤝 Contributing

1. Fork the repo
2. Add knowledge base documents in `knowledge_base/`
3. Extend `agent_config.py` with new focus areas or roles
4. Submit a PR

---

## 📄 License

MIT License — free to use, modify, and deploy.

---

*Built with ❤️ using IBM Watsonx.ai Granite + FAISS RAG + Flask*
