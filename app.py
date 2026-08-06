import os
import json
import ipaddress
import secrets
import socket
import requests
from datetime import datetime, date
from urllib.parse import urljoin, urlparse

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from icalendar import Calendar

# ── Config ────────────────────────────────────────────────────────────────────
app = Flask(__name__)

# Taille maximale acceptée pour un fichier ICS, téléversé comme téléchargé.
MAX_ICS_BYTES = 10 * 1024 * 1024

# Sans SECRET_KEY explicite, une clé aléatoire est tirée à chaque démarrage : les
# sessions ne survivent pas à un redémarrage, ce qui vaut mieux qu'une valeur par
# défaut publique, laquelle rendrait les cookies de session forgeables.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=MAX_ICS_BYTES,
)

CLIENT_SECRETS_FILE = os.environ.get("GOOGLE_CLIENT_SECRETS", "credentials.json")
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Autorise HTTP pour le callback OAuth local. Acceptable uniquement parce que le
# serveur n'écoute que sur 127.0.0.1 (voir le point d'entrée en fin de fichier).
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")


# ── Helpers ───────────────────────────────────────────────────────────────────
# Les sessions Flask sont signées mais NON chiffrées : leur contenu est lisible en
# clair par le navigateur. Aucun jeton n'y est donc placé — le cookie ne porte qu'un
# identifiant opaque, les credentials restent en mémoire du processus. Corollaire :
# une déconnexion à chaque redémarrage, et un seul processus (pas de workers).
_CREDENTIALS_STORE = {}


def get_credentials():
    """Reconstruit les credentials Google depuis le stockage serveur."""
    sid = session.get("sid")
    data = _CREDENTIALS_STORE.get(sid) if sid else None
    if not data:
        return None
    return Credentials(**data)


def store_credentials(creds):
    """Conserve les credentials côté serveur ; le cookie ne reçoit qu'une référence."""
    sid = session.get("sid")
    if not sid:
        sid = secrets.token_urlsafe(32)
        session["sid"] = sid
    _CREDENTIALS_STORE[sid] = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    }


def clear_credentials():
    """Oublie les credentials associés à la session courante."""
    sid = session.get("sid")
    if sid:
        _CREDENTIALS_STORE.pop(sid, None)


def _is_public_url(url: str) -> bool:
    """Vérifie qu'une URL vise un hôte public — protection contre les SSRF."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, ValueError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return bool(infos)


def fetch_ics_url(url: str, max_redirects: int = 5) -> bytes:
    """Télécharge un ICS distant en validant l'URL, puis chaque redirection."""
    for _ in range(max_redirects + 1):
        if not _is_public_url(url):
            raise ValueError("URL refusée : seules les adresses HTTP(S) publiques sont acceptées.")

        resp = requests.get(url, timeout=15, allow_redirects=False, stream=True)
        try:
            if resp.is_redirect or resp.is_permanent_redirect:
                location = resp.headers.get("location")
                if not location:
                    raise ValueError("Redirection sans destination.")
                url = urljoin(url, location)
                continue

            resp.raise_for_status()
            content, total = [], 0
            for chunk in resp.iter_content(65536):
                total += len(chunk)
                if total > MAX_ICS_BYTES:
                    raise ValueError(f"Fichier trop volumineux ({MAX_ICS_BYTES // (1024 * 1024)} Mo maximum).")
                content.append(chunk)
            return b"".join(content)
        finally:
            resp.close()

    raise ValueError("Trop de redirections.")


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
@app.errorhandler(413)
def too_large(_):
    """MAX_CONTENT_LENGTH renvoie un 413 brut : on garde le style des autres erreurs."""
    flash(f"❌ Fichier trop volumineux ({MAX_ICS_BYTES // (1024 * 1024)} Mo maximum).", "error")
    return redirect(url_for("index"))


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
            clear_credentials()
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
    clear_credentials()
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
            ics_content = fetch_ics_url(ics_url)
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
    # Écoute volontairement limitée à la boucle locale : le débogueur Werkzeug
    # expose une console d'exécution de code, et l'app manipule des jetons Google.
    # Débogage sur demande explicite : FLASK_DEBUG=1 python app.py
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1", port=5000)
