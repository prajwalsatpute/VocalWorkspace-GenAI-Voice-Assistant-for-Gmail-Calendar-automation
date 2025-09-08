import os
import json
import base64
import datetime
import tempfile, requests, traceback, shlex, subprocess, re
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from openai import OpenAI

from tzlocal import get_localzone_name
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from email.message import EmailMessage
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials as GoogleCredentials
from google_auth_oauthlib.flow import Flow
from flask import redirect, url_for

load_dotenv()

openai_client = OpenAI()

GOOGLE_CREDS_FILE = os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials_web.json")
if os.environ.get("GOOGLE_CREDENTIALS_JSON"):
    try:
        creds_obj = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
        with open(GOOGLE_CREDS_FILE, "w") as _f:
            json.dump(creds_obj, _f)
        try:
            # Restrict file permissions where possible (owner read/write only)
            os.chmod(GOOGLE_CREDS_FILE, 0o600)
        except Exception:
            pass
        print(f"[startup] Wrote Google credentials to {GOOGLE_CREDS_FILE} from env var.")
    except json.JSONDecodeError:
        print("[startup] GOOGLE_CREDENTIALS_JSON is not valid JSON.")
    except Exception as e:
        print("[startup] Failed to write GOOGLE_CREDENTIALS_JSON to file:", e)

if os.environ.get("GOOGLE_TOKEN_JSON"):
    try:
        token_obj = json.loads(os.environ["GOOGLE_TOKEN_JSON"])
        with open("token.json", "w") as _f:
            json.dump(token_obj, _f)
        try:
            os.chmod("token.json", 0o600)
        except Exception:
            pass
        print("[startup] Wrote token.json from env var.")
    except json.JSONDecodeError:
        print("[startup] GOOGLE_TOKEN_JSON is not valid JSON.")
    except Exception as e:
        print("[startup] Failed to write GOOGLE_TOKEN_JSON to token.json:", e)

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/gmail.compose'
]

app = Flask(__name__)

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route("/login-google")
def login_google():
    # Build the Flow and redirect user to Google consent screen
    redirect_uri = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI") or url_for('oauth2callback', _external=True)
    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDS_FILE,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    auth_url, state = flow.authorization_url(
        access_type='offline',      # request refresh token
        include_granted_scopes='true',
        prompt='consent'
    )
    return redirect(auth_url)


@app.route("/oauth2callback")
def oauth2callback():
    redirect_uri = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI") or url_for('oauth2callback', _external=True)
    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDS_FILE,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    try:
        flow.fetch_token(authorization_response=request.url)
    except Exception as e:
        print("[oauth2callback] fetch_token failed:", e)
        return "Authorization failed: " + str(e), 400

    creds = flow.credentials
    try:
        with open("token.json", "w") as f:
            f.write(creds.to_json())
        try:
            os.chmod("token.json", 0o600)
        except Exception:
            pass
        print("[oauth2callback] token.json written successfully.")
    except Exception as e:
        print("[oauth2callback] Failed to write token.json:", e)
        return "Failed to save credentials.", 500

    return """
    <h3>Google authorization complete.</h3>
    <p>You can close this tab and return to the app.</p>
    """

# ---------- Simple auth helper (non-interactive) ----------
def get_google_credentials():
    """
    Returns google.oauth2.credentials.Credentials if token.json exists and is valid.
    If expired with refresh_token, attempt to refresh and save token.json.
    If no usable credentials are available, return None (caller should redirect to /login-google).
    """
    token_path = "token.json"
    creds = None

    # Try to load existing token.json
    if os.path.exists(token_path):
        try:
            creds = GoogleCredentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            print("[get_google_credentials] Failed to load token.json:", e)
            creds = None

    # If expired and refresh token available, refresh
    if creds and hasattr(creds, "expired") and creds.expired and getattr(creds, "refresh_token", None):
        try:
            creds.refresh(GoogleRequest())
            with open(token_path, 'w') as f:
                f.write(creds.to_json())
            print("[get_google_credentials] Refreshed expired credentials.")
            return creds
        except Exception as e:
            print("[get_google_credentials] Failed to refresh credentials:", e)
            return None

    # If valid, return
    if creds and creds.valid:
        return creds

    # No usable credentials available
    return None

# ---------- Intent parsing prompt (OpenAI) ----------
INTENT_PROMPT = """
You are an assistant that extracts intent from a single spoken command related to Gmail or Calendar.
Return strict JSON only with these fields:
{
  "intent": "send_email" | "draft_email" | "create_event" | "modify_event" | "unknown",
  "recipients": ["email1@domain.com", ...],
  "subject": "subject text" or null,
  "body": "email body" or null,
  "start_datetime": "YYYY-MM-DDTHH:MM:SS" or null,
  "end_datetime": "YYYY-MM-DDTHH:MM:SS" or null,
  "title": "meeting title" or null,
  "timezone": "IANA timezone name like Asia/Kolkata" or null,
  "clarify": ["question1", ...]
}
Rules (IMPORTANT):
- Provide strict JSON only. Do not add any commentary outside the JSON.
- For datetimes:
  - If the user mentions a local time (e.g., "tomorrow at 10 AM") and you can infer the user's timezone, return ISO datetimes in that timezone (e.g. "2025-09-08T10:00:00") and set "timezone" to an IANA name (e.g. "Asia/Kolkata").
  - If you cannot reliably infer the timezone, return naive ISO datetimes (YYYY-MM-DDTHH:MM:SS without offset) and set "timezone" to null; the backend will assume the server/user local timezone.
- **Auto-fill sensible defaults (do this instead of asking trivial questions):**
  - If the user requests creating a meeting but **does not specify a title**, set `"title"` to a reasonable default: prefer `"Meeting with <participant>"` if attendees are known, otherwise `"Meeting"` or `"Meeting - <short excerpt of body>"`.
  - If the user does not specify an end time, set `"end_datetime"` to be **one hour after** `"start_datetime"`.
  - If the user does not specify a meeting duration, assume **1 hour** unless explicitly requested otherwise.
- **When to clarify (only ask when essential):**
  - Ask clarifying questions only if a *required* piece of information is missing or ambiguous such that you cannot safely act — for example:
    - Email recipient is missing or ambiguous (e.g., "HR" with no clear mapping) → ask which email address to use.
    - The time is ambiguous (e.g., "this evening" without a resolvable time) and you cannot infer a concrete start time → ask for a specific hour.
    - The user explicitly asked to confirm before sending (e.g., "Send this now") — if unsure, ask for confirmation.
  - **Do not** ask for title or end time when a sensible default can be applied as above.
- For recipients: return email addresses if available; if the user gives a name (e.g., "HR", "finance team") and you cannot resolve it to an email, set recipients to [] and add a clarifying question asking for the specific email.
- Keep answers minimal and factual inside the JSON. No extra fields.
Examples:
User: "Send an email to HR asking for the updated hiring report"
-> If you cannot map "HR" to an email, set recipients=[] and include clarify like ["Which HR email should I use?"]
User: "Schedule a meeting tomorrow at 10 AM with the finance team"
-> Return start_datetime as the inferred ISO for tomorrow at 10:00, timezone as an IANA name if you can infer it, set end_datetime to one hour later, set title to "Meeting with finance team" (or similar), and clarify only if recipients/time are ambiguous.
Now parse this command:
---
COMMAND: \"\"\"__CMD__\"\"\" 
"""


def parse_intent_with_openai(command_text):
    prompt = INTENT_PROMPT.replace("__CMD__", command_text)

    if not os.environ.get("OPENAI_API_KEY"):
        print("OpenAI API key not set (OPENAI_API_KEY).")
        return {
            "intent":"unknown",
            "recipients":[],
            "subject":None,
            "body":None,
            "start_datetime":None,
            "end_datetime":None,
            "title":None,
            "timezone":None,
            "clarify":["OpenAI API key not configured."]
        }

    models_to_try = ["gpt-4o-mini", "gpt-3.5-turbo"]
    out = None
    last_exception = None
    for model_name in models_to_try:
        try:
            resp = openai_client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are a JSON extractor."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=800
            )
            out = resp.choices[0].message.content
            break
        except Exception as e:
            print(f"OpenAI API error using model {model_name}:", e)
            last_exception = e

    if out is None:
        print("OpenAI final failure:", last_exception)
        return {
            "intent":"unknown",
            "recipients":[],
            "subject":None,
            "body":None,
            "start_datetime":None,
            "end_datetime":None,
            "title":None,
            "timezone":None,
            "clarify":["OpenAI API error. Please try again later."]
        }

    try:
        cleaned = out.strip()

        if cleaned.startswith("```") and "```" in cleaned[3:]:
            cleaned = cleaned[3:-3].strip()

        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].lstrip()

        first_brace = cleaned.find('{')
        last_brace = cleaned.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            json_text = cleaned[first_brace:last_brace+1]
        else:
            json_text = cleaned

        parsed = json.loads(json_text)
        parsed.setdefault("intent", "unknown")
        parsed.setdefault("recipients", [])
        parsed.setdefault("subject", None)
        parsed.setdefault("body", None)
        parsed.setdefault("start_datetime", None)
        parsed.setdefault("end_datetime", None)
        parsed.setdefault("title", None)
        parsed.setdefault("timezone", None)
        parsed.setdefault("clarify", [])

        return parsed

    except Exception:
        print("OpenAI raw output (could not parse):")
        print(out)
        return {
            "intent":"unknown",
            "recipients":[],
            "subject":None,
            "body":None,
            "start_datetime":None,
            "end_datetime":None,
            "title":None,
            "timezone":None,
            "clarify":["Could not parse intent. Please repeat."]
        }

def normalize_parsed_intent(parsed):
    parsed.setdefault("intent", "unknown")
    parsed.setdefault("recipients", [])
    parsed.setdefault("subject", None)
    parsed.setdefault("body", None)
    parsed.setdefault("start_datetime", None)
    parsed.setdefault("end_datetime", None)
    parsed.setdefault("title", None)
    parsed.setdefault("timezone", None)
    parsed.setdefault("clarify", [])

    try:
        local_tz_name = get_localzone_name()  # e.g., "Asia/Kolkata"
    except Exception:
        local_tz_name = "UTC"
    if not parsed.get("timezone"):
        parsed["timezone"] = local_tz_name

    tz = ZoneInfo(parsed["timezone"])
    def _parse_iso_to_aware(iso_str):
        if not iso_str:
            return None
        try:
            d = datetime.fromisoformat(iso_str)
        except Exception:
            try:
                d = datetime.fromisoformat(iso_str + "T00:00:00")
            except Exception:
                return None
        if d.tzinfo is None:
            d = d.replace(tzinfo=tz)
        return d

    start = parsed.get("start_datetime")
    start_dt = _parse_iso_to_aware(start)
    if start_dt:
        parsed["start_datetime"] = start_dt.isoformat()

    end_dt = _parse_iso_to_aware(parsed.get("end_datetime"))
    if parsed.get("intent") in ["create_event", "modify_event"]:
        if start_dt and not end_dt:
            end_dt = start_dt + timedelta(hours=1)
            parsed["end_datetime"] = end_dt.isoformat()
        elif start_dt and end_dt:
            parsed["end_datetime"] = end_dt.isoformat()
        if not parsed.get("title"):
            r = parsed.get("recipients") or []
            if r:
                parsed["title"] = "Meeting with " + (", ".join([e.split('@')[0] for e in r])[:120])
            else:
                if parsed.get("body"):
                    words = parsed["body"].split()
                    parsed["title"] = "Meeting - " + " ".join(words[:6])
                else:
                    parsed["title"] = "Meeting"

    if start_dt:
        now = datetime.now(tz)
        tolerance = timedelta(seconds=60)
        if start_dt < (now - tolerance):
            max_days = 30
            days_moved = 0
            duration = None
            if end_dt:
                duration = end_dt - start_dt

            new_start = start_dt
            while new_start < (now - tolerance) and days_moved < max_days:
                new_start = new_start + timedelta(days=1)
                days_moved += 1

            if new_start >= (now - tolerance):
                if days_moved > 0:
                    print(f"[normalize] start_datetime was in the past; advanced by {days_moved} day(s) from {start_dt.isoformat()} to {new_start.isoformat()}")
                start_dt = new_start
                parsed["start_datetime"] = start_dt.isoformat()
                if duration:
                    end_dt = start_dt + duration
                    parsed["end_datetime"] = end_dt.isoformat()
                else:
                    end_dt = start_dt + timedelta(hours=1)
                    parsed["end_datetime"] = end_dt.isoformat()
            else:
                hour = start_dt.hour
                minute = start_dt.minute
                second = start_dt.second
                candidate = datetime(now.year, now.month, now.day, hour, minute, second, tzinfo=tz)
                if candidate <= now:
                    candidate = candidate + timedelta(days=1)
                print(f"[normalize] parsed start was far in the past; using next-occurrence fallback. from {start_dt.isoformat()} -> {candidate.isoformat()}")
                start_dt = candidate
                parsed["start_datetime"] = start_dt.isoformat()
                if duration:
                    end_dt = start_dt + duration
                    parsed["end_datetime"] = end_dt.isoformat()
                else:
                    end_dt = start_dt + timedelta(hours=1)
                    parsed["end_datetime"] = end_dt.isoformat()

    if parsed.get("intent") in ["send_email", "draft_email"]:
        if not parsed.get("recipients"):
            if not any("email" in q.lower() or "recipient" in q.lower() for q in (parsed.get("clarify") or [])):
                parsed["clarify"] = parsed.get("clarify", []) + ["Which email address should I use for the recipient?"]

    return parsed

# ---------- Gmail helper ----------
def gmail_send_message(creds, to_emails, subject, body_text, send=True):
    service = build('gmail', 'v1', credentials=creds)
    message = EmailMessage()
    message['To'] = ','.join(to_emails)
    message['From'] = 'me'
    message['Subject'] = subject or ''
    message.set_content(body_text or '')
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    payload = {'raw': raw}
    if send:
        msg = service.users().messages().send(userId='me', body=payload).execute()
        return msg
    else:
        draft = service.users().drafts().create(userId='me', body={'message':payload}).execute()
        return draft
    
def _ensure_aware_iso(dt_iso, local_tz_name):
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(dt_iso)
    except Exception:
        try:
            dt = datetime.fromisoformat(dt_iso + "T00:00:00")
        except Exception:
            raise ValueError(f"Unrecognized datetime format: {dt_iso}")

    if dt.tzinfo is None:
        tz = ZoneInfo(local_tz_name)
        dt = dt.replace(tzinfo=tz)
    return dt.isoformat(), dt


# ---------- Calendar helper ----------
def calendar_create_event(creds, start_iso, end_iso, summary, attendees_emails=None, tz_name=None):
    service = build('calendar', 'v3', credentials=creds)
    if tz_name:
        local_tz_name = tz_name
    else:
        try:
            local_tz_name = get_localzone_name()  # e.g., "Asia/Kolkata"
        except Exception:
            local_tz_name = "UTC"
    try:
        start_iso_with_tz, start_dt = _ensure_aware_iso(start_iso, local_tz_name)
    except Exception as e:
        raise ValueError(f"Invalid start_datetime: {e}")
    if end_iso:
        try:
            end_iso_with_tz, end_dt = _ensure_aware_iso(end_iso, local_tz_name)
        except Exception as e:
            raise ValueError(f"Invalid end_datetime: {e}")
    else:
        from datetime import timedelta
        end_dt = start_dt + timedelta(hours=1)
        end_iso_with_tz = end_dt.isoformat()

    event = {
        'summary': summary or 'Meeting',
        'start': {'dateTime': start_iso_with_tz, 'timeZone': local_tz_name},
        'end': {'dateTime': end_iso_with_tz, 'timeZone': local_tz_name},
    }
    if attendees_emails:
        event['attendees'] = [{'email': e} for e in attendees_emails]
    created = service.events().insert(calendarId='primary', body=event).execute()
    return created

# ---------- API endpoints ----------
@app.route('/process-text', methods=['POST'])
def process_text():
    data = request.json or {}
    text = data.get('text','')

    # read client timezone provided by the browser (preferred)
    client_tz = None
    if isinstance(data, dict):
        client_tz = data.get('client_timezone') or None
    # fallback to header if browser sent it that way
    if not client_tz:
        client_tz = request.headers.get('X-Client-Timezone') or None

    # parse intent from LLM
    parsed = parse_intent_with_openai(text)

    # if client timezone provided by browser, prefer that (use before normalization)
    if client_tz:
        parsed['timezone'] = client_tz

    try:

        text_lower = (text or "").lower()
        relative_terms = ["today", "tomorrow", "tonight", "this morning", "this afternoon", "this evening", "next "]
        is_relative = any(rt in text_lower for rt in relative_terms)

        if is_relative:
            try:
                local_tz_name = get_localzone_name()
            except Exception:
                local_tz_name = "UTC"
            parsed['timezone'] = local_tz_name

            def _strip_offset_from_iso(iso_str):
                if not iso_str:
                    return iso_str
                iso_str = iso_str.strip()
                if iso_str.endswith("Z"):
                    return iso_str[:-1]
                m = re.match(r'^(?P<base>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?P<tzoffset>[+-]\d{2}:\d{2})$', iso_str)
                if m:
                    return m.group('base')
                m2 = re.match(r'^(?P<base>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+)(?P<tzoffset>[+-]\d{2}:\d{2})$', iso_str)
                if m2:
                    return m2.group('base')
                return iso_str

            if parsed.get('start_datetime'):
                parsed['start_datetime'] = _strip_offset_from_iso(parsed['start_datetime'])
            if parsed.get('end_datetime'):
                parsed['end_datetime'] = _strip_offset_from_iso(parsed['end_datetime'])

    except Exception as e:
        print("Warning: relative-time handling error:", e)

    # 2) Normalize and autofill sensible defaults (timezone, end time, title, minimal clarifications)
    parsed = normalize_parsed_intent(parsed)
    if parsed.get('clarify'):
        return jsonify({"status":"clarify", "questions": parsed['clarify'], "message": parsed['clarify'][0]})
    creds = get_google_credentials()
    if not creds:
        login_url = url_for('login_google', _external=True)
        return jsonify({
            "status": "auth_required",
            "message": "Google authorization required. Please open the provided URL to authorize.",
            "auth_url": login_url
        }), 401

    try:
        # ---------------- Email handling (draft-first) ----------------
        if parsed['intent'] in ['send_email','draft_email']:
            if parsed.get('body'):
                try:
                    polish_resp = openai_client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role":"user","content":f"Polish this email for professionalism, keep length similar:\n\n{parsed['body']}"}
                        ],
                        temperature=0.2,
                        max_tokens=400
                    )
                    polished = polish_resp.choices[0].message.content.strip()
                except Exception as e:
                    print("Polish error:", e)
                    polished = parsed.get('body') or ''
            else:
                polished = parsed.get('body') or ''

            print("\n--- Polished email preview ---")
            print("To: ", parsed.get('recipients') or [])
            print("Subject: ", parsed.get('subject') or 'No subject')
            print("Body:\n", polished)
            print("--- end preview ---\n")

            EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

            def sanitize_recipient(raw):
                if not raw or not isinstance(raw, str):
                    return raw
                s = raw.strip()
                s = s.replace('"', '').replace("'", "")
                s = re.sub(r'\s+at\s+', '@', s, flags=re.IGNORECASE)
                s = re.sub(r'\s+dot\s+', '.', s, flags=re.IGNORECASE)
                s = s.replace(' ', '')
                if '@' in s:
                    local, domain = s.split('@', 1)
                    s = local + '@' + domain.lower()
                return s

            def is_valid_email(addr):
                return bool(addr and isinstance(addr, str) and EMAIL_RE.match(addr))

            recipients = parsed.get('recipients') or []
            sanitized = []
            invalids = []
            for r in recipients:
                newr = sanitize_recipient(r)
                if is_valid_email(newr):
                    sanitized.append(newr)
                else:
                    invalids.append({"original": r, "sanitized": newr})

            if not sanitized:
                if recipients == []:
                    return jsonify({"status":"clarify", "questions":["Who should I send this to?"], "message":"Who should I send this to?"})
                msgs = []
                for inv in invalids:
                    orig = inv.get('original') or ''
                    msgs.append(f"Could not parse recipient '{orig}'. Please provide a valid email address.")
                return jsonify({"status":"clarify", "questions": msgs, "message": msgs[0]})
            parsed['recipients'] = sanitized
            try:
                draft = gmail_send_message(
                    creds,
                    parsed.get('recipients') or [],
                    parsed.get('subject') or 'No subject',
                    polished,
                    send=False   # create draft
                )
                try:
                    draft_id = None
                    if isinstance(draft, dict):
                        draft_id = draft.get('id') or (draft.get('draft', {}) and draft.get('draft').get('id'))
                    print(f"[process_text] Draft created. draft_id={draft_id}, raw keys={list(draft.keys()) if isinstance(draft, dict) else type(draft)}")
                except Exception as _e:
                    print("[process_text] Warning: unable to log draft details:", _e)

            except Exception as e:
                print("Draft creation error:", e)
                return jsonify({"status":"error","message": str(e)}), 500

            draft_id = None
            if isinstance(draft, dict):
                draft_id = draft.get('id') or (draft.get('draft', {}) and draft.get('draft').get('id'))

            return jsonify({
                "status": "ok",
                "message": "Draft created. Review the polished email and click Send Now if you want to send it.",
                "polished": polished,
                "draft_id": draft_id,
                "raw": draft
            })


        # ---------------- Calendar handling ----------------
        elif parsed['intent'] in ['create_event','modify_event']:
            start = parsed.get('start_datetime')
            end = parsed.get('end_datetime')

            if start is None:
                return jsonify({"status":"clarify","questions":["When should I schedule it?"], "message":"When should I schedule it?"})
            if end is None:
                try:
                    dt = datetime.datetime.fromisoformat(start)
                    end = (dt + datetime.timedelta(hours=1)).isoformat()
                except Exception:
                    end = None

            tz_from_model = parsed.get('timezone')  # may be IANA like "Asia/Kolkata"
            created = calendar_create_event(
                creds,
                start,
                end,
                parsed.get('title') or 'Meeting',
                parsed.get('recipients'),
                tz_name=tz_from_model
            )

            return jsonify({"status":"ok","message": f"Created event: {created.get('htmlLink')}", "raw":created})

        else:
            return jsonify({"status":"unknown","message":"Sorry, I couldn't understand the command."})

    except Exception as e:
        print("Error in process_text():", e)
        return jsonify({"status":"error","message":str(e)}), 500

@app.route('/confirm-send', methods=['POST'])
def confirm_send():
    try:
        data = request.get_json(force=True, silent=True) or {}
        draft_id = data.get('draft_id')
        print(f"[confirm_send] Received confirm-send request. draft_id={draft_id}")
        if not draft_id:
            return jsonify({"status":"error","message":"draft_id required"}), 400

        creds = get_google_credentials()
        service = build('gmail', 'v1', credentials=creds)
        try:
            fetched = service.users().drafts().get(userId='me', id=draft_id).execute()
            print("[confirm_send] Draft fetched successfully. keys:", list(fetched.keys()))
        except Exception as e_get:
            print("[confirm_send] Warning: could not fetch draft before send:", repr(e_get))
        sent = service.users().drafts().send(userId='me', body={'id': draft_id}).execute()
        print("[confirm_send] Draft sent OK. response keys:", list(sent.keys()) if isinstance(sent, dict) else type(sent))
        return jsonify({"status":"ok","message":"Email sent successfully.", "raw": sent})
    except Exception as e:
        import traceback
        print("confirm_send exception:", repr(e))
        traceback.print_exc()
        return jsonify({"status":"error","message": str(e)}), 500


@app.route('/process-audio', methods=['POST'])
def process_audio():
    audio_file = request.files.get('audio')
    if not audio_file:
        return jsonify({"status":"error","message":"No audio file uploaded."}), 400

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(audio_file.filename)[1] or ".webm")
    wav_tmp = None
    try:
        audio_file.save(tmp.name)
        tmp.flush()

        size = None
        try:
            size = os.path.getsize(tmp.name)
        except:
            pass
        print(f"[process-audio] saved upload to {tmp.name}, size={size}")

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            msg = "OpenAI API key not configured (OPENAI_API_KEY missing)"
            print("[process-audio] ERROR:", msg)
            return jsonify({"status":"error","message": msg}), 500
        def call_whisper(file_path):
            openai_url = "https://api.openai.com/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {api_key}"}
            files = {"file": (os.path.basename(file_path), open(file_path, "rb"))}
            data = {"model": "whisper-1"}
            try:
                r = requests.post(openai_url, headers=headers, data=data, files=files, timeout=120)
                return r
            except requests.exceptions.RequestException as e:
                raise
        try:
            print("[process-audio] Trying direct transcription of uploaded file...")
            resp = call_whisper(tmp.name)
        except Exception as e:
            print("[process-audio] Network error calling Whisper (direct):", e)
            traceback.print_exc()
            return jsonify({"status":"error","message":"Network error during transcription","detail": str(e)}), 500
        if resp.status_code == 200:
            try:
                trans_json = resp.json()
                transcript = trans_json.get("text", "").strip()
            except Exception as e:
                print("[process-audio] Failed to parse Whisper JSON (direct):", e)
                return jsonify({"status":"error","message":"Failed to parse transcription response","detail": str(e)}), 500

            if transcript:
                print("[process-audio] Direct transcription success:", transcript[:200])

                # forward client timezone into the internal call
                client_tz = request.headers.get('X-Client-Timezone') or None
                forward_json = {'text': transcript}
                if client_tz:
                    forward_json['client_timezone'] = client_tz

                resp2 = app.test_client().post('/process-text', json=forward_json)
                forwarded = resp2.get_json()
                return jsonify({"status":"ok","transcript": transcript, **(forwarded or {})})

        else:
            try:
                err_json = resp.json()
            except Exception:
                err_json = {"text": resp.text}
            err_msg = err_json.get("error", {}).get("message") if isinstance(err_json, dict) else str(err_json)
            print(f"[process-audio] Whisper direct error status={resp.status_code}, message={err_msg}")
            if resp.status_code not in (400, 415, 422):
                return jsonify({"status":"error","message":"Transcription failed","detail": err_json}), 500
            else:
                print("[process-audio] Attempting ffmpeg conversion to WAV and retry...")

        wav_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        wav_tmp.close()  # will be written by ffmpeg
        ffmpeg_cmd = f"ffmpeg -y -i {shlex.quote(tmp.name)} -ar 16000 -ac 1 {shlex.quote(wav_tmp.name)}"
        print("[process-audio] Running ffmpeg:", ffmpeg_cmd)
        try:
            completed = subprocess.run(ffmpeg_cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            print("[process-audio] ffmpeg completed. stdout:", completed.stdout[:400], "stderr:", completed.stderr[:400])
        except subprocess.CalledProcessError as cpe:
            print("[process-audio] ffmpeg failed:", cpe.returncode)
            print("ffmpeg stdout:", getattr(cpe, "stdout", None))
            print("ffmpeg stderr:", getattr(cpe, "stderr", None))
            return jsonify({"status":"error","message":"Audio conversion failed","detail": {"returncode": cpe.returncode, "stderr": cpe.stderr}}), 500

        print("[process-audio] Converted to wav at", wav_tmp.name, "size=", os.path.getsize(wav_tmp.name))
        try:
            resp_retry = call_whisper(wav_tmp.name)
        except Exception as e:
            print("[process-audio] Network error calling Whisper (retry):", e)
            traceback.print_exc()
            return jsonify({"status":"error","message":"Network error during transcription (retry)","detail": str(e)}), 500

        print("[process-audio] Whisper retry status:", resp_retry.status_code)
        try:
            body = resp_retry.text
            print("[process-audio] Whisper retry body (truncated):", body[:1000])
        except:
            pass

        if resp_retry.status_code != 200:
            try:
                errj = resp_retry.json()
            except:
                errj = {"text": resp_retry.text}
            return jsonify({"status":"error","message":"Transcription failed (after conversion)","detail": errj}), 500

        try:
            trans_json = resp_retry.json()
            transcript = trans_json.get("text", "").strip()
        except Exception as e:
            print("[process-audio] Failed to parse transcription JSON after retry:", e)
            return jsonify({"status":"error","message":"Failed to parse transcription response (retry)","detail": str(e)}), 500

        if not transcript:
            return jsonify({"status":"error","message":"Empty transcript returned after conversion","detail": trans_json}), 500

        print("[process-audio] Transcription (after conversion) OK:", transcript[:200])
        try:
            client_tz = request.headers.get('X-Client-Timezone') or None
            forward_json = {'text': transcript}
            if client_tz:
                forward_json['client_timezone'] = client_tz

            resp2 = app.test_client().post('/process-text', json=forward_json)
            forwarded = resp2.get_json()
        except Exception as e:
            print("[process-audio] failed to forward transcript to /process-text:")
            traceback.print_exc()
            return jsonify({"status":"error","message":"Failed to forward transcript","detail": str(e)}), 500

        return jsonify({"status":"ok","transcript": transcript, **(forwarded or {})})

    except Exception as e:
        print("[process-audio] unexpected server error:")
        traceback.print_exc()
        return jsonify({"status":"error","message":"Server error during transcription","detail": str(e)}), 500
    finally:
        try:
            tmp.close()
            os.unlink(tmp.name)
        except Exception:
            pass
        if wav_tmp:
            try:
                os.unlink(wav_tmp.name)
            except Exception:
                pass

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)