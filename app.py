import os
import json
import requests
from datetime import datetime, date

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from icalendar import Calendar

# ── Config ────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")

CLIENT_SECRETS_FILE = os.environ.get("GOOGLE_CLIENT_SECRETS", "credentials.json")
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Allow HTTP for local dev (remove in production)
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_credentials():
    """Reconstruit les credentials Google depuis la session."""
    if "credentials" not in session:
        return None
    return Credentials(**session["credentials"])


def store_credentials(creds):
    """Sauvegarde les credentials dans la session."""
    session["credentials"] = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    }


def ics_component_to_google_event(component):
    """Convertit un VEVENT iCalendar en dict compatible Google Calendar API."""
    event = {}

    if component.get("summary"):
        event["summary"] = str(component.get("summary"))
    if component.get("description"):
        event["description"] = str(component.get("description"))
    if component.get("location"):
        event["location"] = str(component.get("location"))

    dtstart = component.get("dtstart")
    dtend = component.get("dtend")
    if not dtstart:
        raise ValueError("Événement sans date de début — ignoré.")

    start_dt = dtstart.dt
    end_dt = dtend.dt if dtend else None

    if isinstance(start_dt, datetime):
        tz = str(start_dt.tzinfo) if start_dt.tzinfo else "UTC"
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=__import__("pytz").utc)
        event["start"] = {"dateTime": start_dt.isoformat(), "timeZone": tz}
        if end_dt:
            if isinstance(end_dt, datetime):
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=__import__("pytz").utc)
                event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": tz}
            else:
                event["end"] = {"date": end_dt.isoformat()}
        else:
            event["end"] = event["start"]
    else:
        # Journée entière
        event["start"] = {"date": start_dt.isoformat()}
        event["end"] = {"date": end_dt.isoformat() if end_dt else start_dt.isoformat()}

    # UID pour éviter les doublons (importMode)
    if component.get("uid"):
        event["iCalUID"] = str(component.get("uid"))

    return event


def parse_ics(content: bytes):
    """Parse le contenu ICS et retourne la liste des VEVENTs."""
    cal = Calendar.from_ical(content)
    events = []
    for component in cal.walk():
        if component.name == "VEVENT":
            events.append(component)
    return events


def list_calendars(service):
    """Retourne la liste des agendas de l'utilisateur."""
    result = service.calendarList().list().execute()
    return result.get("items", [])


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    creds = get_credentials()
    calendars = []
    user_email = None
    if creds:
        try:
            service = build("calendar", "v3", credentials=creds)
            calendars = list_calendars(service)
            # Récupère l'email depuis le calendrier primary
            primary = next((c for c in calendars if c.get("primary")), None)
            if primary:
                user_email = primary.get("id")
        except Exception:
            session.pop("credentials", None)
    return render_template("index.html", authenticated=bool(creds),
                           calendars=calendars, user_email=user_email)


@app.route("/login")
def login():
    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = url_for("oauth2callback", _external=True)
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["oauth_state"] = state
    return redirect(auth_url)


@app.route("/oauth2callback")
def oauth2callback():
    state = session.get("oauth_state")
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state
    )
    flow.redirect_uri = url_for("oauth2callback", _external=True)
    flow.fetch_token(authorization_response=request.url)
    store_credentials(flow.credentials)
    flash("✅ Connecté à Google Calendar !", "success")
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Déconnecté.", "info")
    return redirect(url_for("index"))


@app.route("/import", methods=["POST"])
def import_ics():
    creds = get_credentials()
    if not creds:
        flash("Veuillez vous connecter d'abord.", "error")
        return redirect(url_for("index"))

    # ── Récupération du contenu ICS ──
    ics_content = None
    source_name = ""

    uploaded_file = request.files.get("file")
    ics_url = request.form.get("url", "").strip()

    if uploaded_file and uploaded_file.filename:
        ics_content = uploaded_file.read()
        source_name = uploaded_file.filename
    elif ics_url:
        try:
            resp = requests.get(ics_url, timeout=15)
            resp.raise_for_status()
            ics_content = resp.content
            source_name = ics_url
        except Exception as e:
            flash(f"❌ Impossible de télécharger l'URL : {e}", "error")
            return redirect(url_for("index"))
    else:
        flash("❌ Aucun fichier ou URL fourni.", "error")
        return redirect(url_for("index"))

    # ── Parse ICS ──
    try:
        components = parse_ics(ics_content)
    except Exception as e:
        flash(f"❌ Fichier ICS invalide : {e}", "error")
        return redirect(url_for("index"))

    if not components:
        flash("⚠️ Aucun événement trouvé dans le fichier.", "warning")
        return redirect(url_for("index"))

    # ── Import dans Google Calendar ──
    calendar_id = request.form.get("calendar_id", "primary")
    service = build("calendar", "v3", credentials=creds)

    imported, skipped, errors_list = 0, 0, []

    for component in components:
        try:
            event_body = ics_component_to_google_event(component)
            # Utilise import() si l'événement a un iCalUID, sinon insert()
            if "iCalUID" in event_body:
                service.events().import_(calendarId=calendar_id, body=event_body).execute()
            else:
                service.events().insert(calendarId=calendar_id, body=event_body).execute()
            imported += 1
        except Exception as e:
            summary = str(component.get("summary", "sans titre"))
            errors_list.append(f"« {summary} » : {e}")
            skipped += 1

    # ── Résumé ──
    msg = f"✅ {imported} événement(s) importé(s) depuis « {source_name} »."
    if skipped:
        msg += f" ⚠️ {skipped} ignoré(s)."
    flash(msg, "success" if imported else "warning")

    if errors_list:
        for err in errors_list[:5]:  # Limite l'affichage
            flash(f"  › {err}", "error")

    return redirect(url_for("index"))


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
