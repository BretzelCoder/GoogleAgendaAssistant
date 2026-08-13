import os
import json
import ipaddress
import secrets
import socket
import requests
from datetime import datetime, date, timedelta
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import (Flask, render_template, request, redirect, url_for, session,
                   flash, jsonify, Response)
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from icalendar import Calendar

import siga

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


# Vérificateurs PKCE des flux OAuth en cours. Même principe que les credentials :
# rien dans le cookie, tout en mémoire du processus.
_CODE_VERIFIER_STORE = {}


def store_code_verifier(verifier):
    """Retient le vérificateur PKCE du flux en cours jusqu'au retour de Google."""
    sid = session.get("sid")
    if not sid:
        sid = secrets.token_urlsafe(32)
        session["sid"] = sid
    _CODE_VERIFIER_STORE[sid] = verifier


def pop_code_verifier():
    """Récupère et consomme le vérificateur PKCE — il ne sert qu'une fois."""
    sid = session.get("sid")
    return _CODE_VERIFIER_STORE.pop(sid, None) if sid else None


# Plannings SIGA extraits, en attente de validation par l'utilisateur. Même
# principe que _CREDENTIALS_STORE : rien dans le cookie, tout en mémoire du
# processus. Le mot de passe universitaire n'y figure jamais — il sert à ouvrir
# la session SIGA puis est abandonné avec elle.
_PLANNING_STORE = {}


def store_planning(data):
    """Conserve le planning extrait pour l'écran de prévisualisation."""
    sid = session.get("sid")
    if not sid:
        sid = secrets.token_urlsafe(32)
        session["sid"] = sid
    _PLANNING_STORE[sid] = data


def get_planning():
    sid = session.get("sid")
    return _PLANNING_STORE.get(sid) if sid else None


def clear_planning():
    sid = session.get("sid")
    if sid:
        _PLANNING_STORE.pop(sid, None)


def _parse_date(value, default):
    """Lit une date `AAAA-MM-JJ` issue d'un `<input type=date>`."""
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return default


def _valid_timezone(name):
    """Valide un identifiant IANA ; Google rejette l'événement sinon."""
    name = (name or "").strip() or siga.DEFAULT_TIMEZONE
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, ModuleNotFoundError):
        return siga.DEFAULT_TIMEZONE
    return name


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

    planning = get_planning()
    today = date.today()
    return render_template(
        "index.html",
        authenticated=bool(creds),
        calendars=calendars,
        user_email=user_email,
        planning=planning,
        siga_servers=siga.SERVERS,
        siga_planning_url=siga.PLANNING_URL,
        siga_timezone=siga.DEFAULT_TIMEZONE,
        # Bornes par défaut de la récurrence : un semestre approximatif, que
        # l'utilisateur ajuste dans le formulaire.
        default_start=today.isoformat(),
        default_end=(today + timedelta(days=120)).isoformat(),
    )


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
    # PKCE : `authorization_url()` vient de tirer un code_verifier dont seule
    # l'empreinte part chez Google. Le callback reconstruit un Flow neuf, qui
    # l'ignorerait — Google refuserait alors l'échange (« Missing code verifier »).
    store_code_verifier(flow.code_verifier)
    return redirect(auth_url)


@app.route("/oauth2callback")
def oauth2callback():
    state = session.get("oauth_state")
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state,
        code_verifier=pop_code_verifier(),
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = url_for("oauth2callback", _external=True)
    flow.fetch_token(authorization_response=request.url)
    store_credentials(flow.credentials)
    flash("✅ Connecté à Google Calendar !", "success")
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    clear_credentials()
    clear_planning()
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


# ── SIGA (planning universitaire) ─────────────────────────────────────────────
@app.route("/siga/planning", methods=["POST"])
def siga_planning():
    """Se connecte à SIGA, lit la page de planning et prépare la prévisualisation.

    Les identifiants universitaires ne servent qu'ici : la session SIGA est
    fermée avant de rendre la main, et seuls les créneaux extraits survivent à
    la requête.
    """
    if not get_credentials():
        flash("Connectez-vous d'abord à Google Calendar.", "error")
        return redirect(url_for("index"))

    login = request.form.get("siga_login", "").strip()
    password = request.form.get("siga_password", "")
    server = request.form.get("siga_server", "usm.cl").strip()
    planning_url = request.form.get("siga_url", "").strip() or siga.PLANNING_URL

    client = siga.SigaClient(url_guard=_is_public_url)
    transcript, landing = [], ""
    try:
        client.login(login, password, server)
        documents = client.fetch_planning(planning_url)
        transcript, landing = client.transcript, client.landing_url
    except siga.SigaError as e:
        flash(f"❌ {e}", "error")
        return redirect(url_for("index"))
    except Exception as e:  # noqa: BLE001 — le portail est hors de notre contrôle
        flash(f"❌ Échec de la lecture du planning : {e}", "error")
        return redirect(url_for("index"))
    finally:
        client.close()
        password = None

    blocks, diagnostic = siga.parse_horario(documents)
    # Code HTTP et taille de chaque réponse : une page vide et une page
    # inattendue donnent toutes deux zéro créneau, et seul ce journal les sépare.
    diagnostic["requetes"] = transcript
    # Où l'authentification a effectivement abouti : le menu de l'étudiant part
    # de là, et une arrivée inattendue explique à elle seule un planning vide.
    diagnostic["arrivee_apres_login"] = landing
    if not blocks:
        flash(
            "⚠️ Connexion réussie, mais aucun créneau n'a pu être extrait de la page. "
            "Consultez /siga/diagnostic pour voir ce qui a été récupéré.", "warning"
        )

    store_planning({
        "blocks": [b.to_dict() for b in blocks],
        "diagnostic": diagnostic,
        "url": planning_url,
        "fetched_at": datetime.now().strftime("%d/%m/%Y à %H:%M"),
        # Conservé pour /siga/diagnostic quand l'extraction échoue ; jamais
        # renvoyé dans une page normale, et effacé avec le reste à la déconnexion.
        "documents": [(u, h[:200000]) for u, h in documents],
    })

    if blocks:
        review = sum(1 for b in blocks if b.needs_review)
        msg = f"✅ {len(blocks)} créneau(x) trouvé(s) sur le planning SIGA."
        if review:
            msg += f" ⚠️ {review} avec un horaire déduit — à vérifier."
        flash(msg, "success")

    return redirect(url_for("index"))


@app.route("/siga/import", methods=["POST"])
def siga_import():
    """Pousse les créneaux sélectionnés dans Google Calendar, en bloc."""
    creds = get_credentials()
    if not creds:
        flash("Veuillez vous connecter d'abord.", "error")
        return redirect(url_for("index"))

    planning = get_planning()
    if not planning or not planning.get("blocks"):
        flash("❌ Aucun planning en mémoire — relancez la lecture SIGA.", "error")
        return redirect(url_for("index"))

    # Une sélection vide signifie « tout décoché », pas « tout prendre ».
    selected = set(request.form.getlist("blocs"))
    blocks = [siga.ScheduleBlock.from_dict(b) for b in planning["blocks"]
              if b["key"] in selected]
    if not blocks:
        flash("❌ Aucun créneau sélectionné.", "error")
        return redirect(url_for("index"))

    today = date.today()
    start_date = _parse_date(request.form.get("date_debut"), today)
    end_date = _parse_date(request.form.get("date_fin"), today + timedelta(days=120))
    if end_date < start_date:
        flash("❌ La date de fin précède la date de début.", "error")
        return redirect(url_for("index"))

    timezone = _valid_timezone(request.form.get("timezone"))
    term = request.form.get("term", "").strip()
    calendar_id = request.form.get("calendar_id", "primary")

    events = siga.blocks_to_google_events(blocks, start_date, end_date, timezone, term)
    if not events:
        flash("⚠️ Aucun créneau ne tombe dans la période demandée.", "warning")
        return redirect(url_for("index"))

    service = build("calendar", "v3", credentials=creds)
    imported, skipped, errors_list = 0, 0, []

    for block, body in events:
        try:
            # `import_` avec un iCalUID déterministe : réexécuter la
            # synchronisation met à jour les événements au lieu d'en créer.
            service.events().import_(calendarId=calendar_id, body=body).execute()
            imported += 1
        except Exception as e:  # noqa: BLE001
            errors_list.append(f"« {block.summary} » ({block.weekday_label}) : {e}")
            skipped += 1

    msg = (f"✅ {imported} cours synchronisé(s) dans Google Calendar "
           f"(du {start_date.strftime('%d/%m/%Y')} au {end_date.strftime('%d/%m/%Y')}).")
    if skipped:
        msg += f" ⚠️ {skipped} en échec."
    flash(msg, "success" if imported else "warning")
    for err in errors_list[:5]:
        flash(f"  › {err}", "error")

    return redirect(url_for("index"))


@app.route("/siga/oublier")
def siga_forget():
    """Vide le planning en mémoire sans toucher à la session Google."""
    clear_planning()
    flash("Planning SIGA oublié.", "info")
    return redirect(url_for("index"))


# Dossier de vidage des pages SIGA. Il reçoit des données personnelles : couvert
# par .gitignore, effacé à chaque appel, et à supprimer une fois le débogage fini.
SIGA_DUMP_DIR = os.environ.get("SIGA_DUMP_DIR", ".siga-dump")


def _dump_documents(documents):
    """Écrit chaque document dans son propre fichier ; renvoie le compte rendu."""
    os.makedirs(SIGA_DUMP_DIR, exist_ok=True)
    for stale in os.listdir(SIGA_DUMP_DIR):
        if stale.endswith(".html"):
            os.remove(os.path.join(SIGA_DUMP_DIR, stale))

    lines = [f"{len(documents)} document(s) écrit(s) dans {os.path.abspath(SIGA_DUMP_DIR)}", ""]
    for index, (url, html) in enumerate(documents, start=1):
        # Le nom du fichier ne vient jamais tel quel de l'URL : seuls les
        # caractères sûrs sont conservés, et le numéro d'ordre garantit l'unicité.
        slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in url.rsplit("/", 1)[-1])
        path = os.path.join(SIGA_DUMP_DIR, f"{index:02d}_{slug[:80]}.html")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"<!-- {url} -->\n{html}")
        lines.append(f"{path}  ({len(html)} caractères)  {url}")
    return lines


@app.route("/siga/diagnostic")
def siga_diagnostic():
    """Renvoie le HTML récupéré sur SIGA, pour comprendre une extraction vide.

    Réservé au débogage local : la page peut contenir des données personnelles,
    ce qui reste acceptable tant que le serveur n'écoute que sur 127.0.0.1.

    `?doc=<fragment>` restreint le dump aux documents dont l'URL contient ce
    fragment : le portail en empile une dizaine, et seul l'un d'eux est en cause.
    `?save=1` les écrit en plus dans `SIGA_DUMP_DIR`, un fichier par document —
    plus maniable qu'une page de 50 000 caractères quand il faut les relire.
    """
    planning = get_planning()
    if not planning:
        return Response("Aucun planning en mémoire.", mimetype="text/plain")

    wanted = request.args.get("doc", "").strip().lower()
    documents = [(u, h) for u, h in planning.get("documents", [])
                 if not wanted or wanted in u.lower()]

    if request.args.get("save"):
        return Response("\n".join(_dump_documents(documents)),
                        mimetype="text/plain; charset=utf-8")

    parts = [f"URL demandée : {planning['url']}",
             f"Extrait le {planning['fetched_at']}"]
    if wanted:
        parts.append(f"Filtre : ?doc={wanted} — {len(documents)} document(s) retenu(s)")
    else:
        parts.append(
            f"Diagnostic : {json.dumps(planning['diagnostic'], ensure_ascii=False, indent=2)}")
    parts += [f"Créneaux extraits : {len(planning['blocks'])}", ""]
    for url, html in documents:
        parts.append("=" * 78)
        parts.append(url)
        parts.append("=" * 78)
        # Sans mention explicite, un corps vide est indiscernable d'un bug de
        # cette page de diagnostic — l'un des deux cas les plus courants ici.
        parts.append(html if html.strip() else "(corps vide — le portail n'a renvoyé aucun contenu)")
    return Response("\n".join(parts), mimetype="text/plain; charset=utf-8")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Écoute volontairement limitée à la boucle locale : le débogueur Werkzeug
    # expose une console d'exécution de code, et l'app manipule des jetons Google.
    # Débogage sur demande explicite : FLASK_DEBUG=1 python app.py
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1", port=5000)
