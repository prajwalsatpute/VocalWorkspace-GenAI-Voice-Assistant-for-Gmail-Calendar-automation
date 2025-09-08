# Voice-enabled GenAI Assistant

This is a assignment project that builds a **voice-enabled assistant** for Gmail and Google Calendar. The assistant understands spoken commands, converts them into actions, and performs tasks like:  

- Sending Gmail emails,  
- Scheduling Google Calendar events,  
- Providing voice/text confirmations.  

---

## Assignment Completion Status   
- ✅ Voice input (speech-to-text using browser or Whisper API)  
- ✅ Intent extraction using OpenAI  
- ✅ Gmail draft creation + email send confirmation  
- ✅ Google Calendar event creation  
- ✅ Clarification handling for missing info  
- ✅ Web demo (index.html + Flask server)  

---

# NOTE : 
**- Codes files(server.py & index.html) which are in app/... directory are not for local system and those are separately attached in different folder called `local system folder` folder. But they follow same folder structure as per deployed.**
**- These files are only separated just to prevent any confusions while running files on local system.**

## Dependencies  

### Python (core libraries)  
Install via `pip install -r requirements.txt`:  
- `flask` – for server and endpoints  
- `python-dotenv` – load environment variables  
- `openai` – call OpenAI API for intent parsing, polishing, Whisper transcription  
- `google-auth-oauthlib` – handle Google OAuth flow  
- `google-api-python-client` – connect to Gmail & Calendar APIs  
- `tzlocal` – detect local timezone  
- `requests` – HTTP requests (used for Whisper API call)  

### System dependency  
- **ffmpeg** – required for audio conversion (when Whisper rejects uploaded format).  
  - Linux: `sudo apt install ffmpeg`  
  - macOS: `brew install ffmpeg`  
  - Windows: download from [ffmpeg.org](https://ffmpeg.org) and add to PATH  

---

## What is `credentials.json`?  
- It’s the **OAuth client credentials** from Google Cloud.  
- You need it to access Gmail & Calendar APIs.  

**Steps to get it:**  
1. Go to [Google Cloud Console](https://console.cloud.google.com/).  
2. Create a project and enable **Gmail API** + **Google Calendar API**.  
3. Go to **APIs & Services → Credentials**.  
4. Create OAuth 2.0 credentials (Application type: **Desktop app**).  
5. Download the file → rename it to `credentials.json` → put it in your project folder.  

The app will then generate a `token.json` after first login (stores your access tokens).  

---

## What is `.env` file?  
- A `.env` file stores **environment variables** securely.  
- In this project, it’s used to keep your **OpenAI API key** (and optionally Google credentials path).  

Contents of `.env`:  
```bash
OPENAI_API_KEY=sk-xxxx <- Generated OpenAI API Key
GOOGLE_CREDENTIALS_PATH=credentials.json
FLASK_ENV = development <- keep it as is
OAUTHLIB_INSECURE_TRANSPORT = 1 <- keep it as is
```  

This keeps secrets out of the code.  

---

## What is `requirements.txt` file?  
- A plain text file listing all Python dependencies with versions.  
- You can install everything at once:  

```bash
pip install -r requirements.txt
```  

Example content:  
```
flask
python-dotenv
openai
google-auth-oauthlib
google-api-python-client
tzlocal
requests
```  

---

## What is `venv` and how to set it up?  
- `venv` (Virtual Environment) is a tool to create isolated Python environments.  
- It ensures dependencies for this project don’t interfere with other Python projects.  

**Steps to set up `venv`:**  (For running on the local system)
1. Create a new virtual environment:  
   ```bash
   python -m venv .venv
   ```  
2. Activate it:  
   - On Linux/Mac:  
     ```bash
     source .venv/bin/activate
     ```  
   - On Windows (PowerShell):  
     ```bash
     .venv\Scripts\activate
     ```  
3. Install dependencies:  
   ```bash
   pip install -r requirements.txt
   ```  
4. To deactivate the environment:  
   ```bash
   deactivate
   ```  

---

## How to Run  
1. Install dependencies:  
   ```bash
   pip install -r requirements.txt
   ```  
2. Set up `.env` with your **OpenAI API key**.  
3. Place `credentials.json` (Google OAuth file) in the project.  
4. Run the server:  
   ```bash
   python3 server.py
   ```  
5. Open [http://localhost:5000](http://localhost:5000) in your browser.  
6. Speak/Record the voice message
7. Do the necessary google authorisation from the terminal generated link → Press Continue
8. Page will open (Page will look like This site can't be reached but it's not an error ust do the step 9)
9. Copy that page link from step 8 and paste it in terminal.

---

## Notes  
- On first run, the server will ask you to copy-paste an **authorization URL** → complete login → paste redirect URL back.  
- A `token.json` will be created so you don’t need to log in again.
- Setting up venv is only for running code on local system.
- **Files which are not uploaded on Github and not Deployed**:
   - .env
   - credentials.json
   - token.json
   
   This is because files contain sensitive information that can be misused.
   These files are to be created and instructions about the files are mentioned above.


## Deployment (Render)

A live deployment of this Voice Assistant is available on Render:

- Public app URL: `https://voice-assistant-3h84.onrender.com`

### How this deployment works

- The backend is a Flask app (`app/server.py`) which exposes endpoints:
  - `GET /` — serves `index.html`
  - `POST /process-text` — handle text intent parsing and create calendar/email drafts
  - `POST /process-audio` — accept audio upload, transcribe via OpenAI Whisper, then forward to `/process-text`
  - `GET /login-google` and `GET /oauth2callback` — handle Google OAuth web flow
  - `POST /confirm-send` — confirm and send a drafted email

- This app uses user-scoped Google OAuth (web flow). When a browser request needs Google access and there is no usable `token.json`, the server returns JSON with `status: "auth_required"` and an `auth_url`. The client UI opens that URL in a new tab, user authorizes, and Google redirects to `/oauth2callback` which saves `token.json` on the server.

### Render setup (notes / checklist)

1. **Create a Web Service** on Render (Static/Docker not needed) and connect to this GitHub repository.
2. **Build command**: leave blank or use default (Render autodetects). If you want:  

### Required Environment Variables (set these in Render → Environment → Environment Variables)

- `OPENAI_API_KEY` — API key for OpenAI (used for intent parsing and email polishing).
- `GOOGLE_CREDENTIALS_JSON` — JSON string of your Google OAuth client credentials (the contents of the downloaded `credentials.json` from Google Cloud). The server writes this to a file on startup.
- Alternatively, upload a `credentials.json` file to the repo (not recommended).
- `GOOGLE_TOKEN_JSON` — optional: JSON of an existing `token.json` (so you pre-authorize the app). If not provided, users will be prompted to authorize in-browser.
- `GOOGLE_OAUTH_REDIRECT_URI` — optional override for the OAuth redirect URI; otherwise the app uses its default `/oauth2callback`.
- `PORT` — (not required) Render sets automatically.

### How to authorize when visiting the public app

1. Visit the app public URL mentioned above and try to schedule a meeting through **Speak Button**.
2. The browser UI opens the Google auth URL in a new tab. Complete the consent flow and allow access. **For now access is inly given to `prajwal.satpute2000@gmail.com`.**
3. After consent, Google redirects to `/oauth2callback`. The app stores `token.json` and you can return to the original tab to retry scheduling.

**Note : Browser popups should be enabled.**