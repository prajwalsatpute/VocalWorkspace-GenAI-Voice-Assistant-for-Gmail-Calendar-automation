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
-** This README.md file is for local system setup, codes files(server.py & index.html) for local system are separately attached in different folder. But they follow same folder structure as per deployed.**
- **These files are only separated just to prevent any confusions while running files on local system.**

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
