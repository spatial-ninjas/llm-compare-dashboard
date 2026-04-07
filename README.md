# OpenAI vs Gemini Comparator

A small local Streamlit app that sends the same prompt to OpenAI and Gemini, then shows the responses side by side with basic metadata.

## Features

- One prompt sent to both providers
- Side-by-side outputs
- Basic metadata:
  - latency
  - input/output/total tokens
  - finish/status info when available
- Adjustable response cap with `max_output_tokens`
- Session history for the current Streamlit session

## Files

- `app.py` — the Streamlit app
- `requirements.txt` — Python dependencies
- `.env.example` — environment variable template

## Setup

### 1. Create and activate a virtual environment

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create `.env`

Copy `.env.example` to `.env` and fill in your keys.

macOS / Linux:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Then edit `.env`:

```env
OPENAI_API_KEY=your_openai_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
```

### 4. Run the app

```bash
streamlit run app.py
```

Open the local URL shown by Streamlit, usually:

`http://localhost:8501`

## Notes

- The response token cap is wired in through the sidebar slider and sent to both APIs.
- This app shows per-call usage metadata, not a guaranteed provider-wide "tokens left" counter.
- Keep `.env` out of Git.
