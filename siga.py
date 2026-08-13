"""Connecteur SIGA — Universidad Técnica Federico Santa María (siga.usm.cl).

Ouvre une session authentifiée sur le portail, récupère la page « Horario del
alumno » et en extrait les blocs de cours, convertis ensuite en événements
Google Calendar récurrents.

Trois particularités du site dictent la forme de ce module :

1. Le portail est protégé par **Queue-it** (salle d'attente virtuelle,
   `usm.queue-it.net`). Une première visite enchaîne plusieurs redirections
   inter-domaines qui déposent un cookie `QueueITAccepted-…` ; sans persistance
   des cookies, on boucle indéfiniment. D'où la `requests.Session` partagée et
   le suivi manuel des redirections.
2. Les pages sont servies en **ISO-8859-1**. Décodées en UTF-8, les accents
   espagnols (« Matemática », « miércoles ») sortent en mojibake et cassent la
   détection des jours.
3. La page de planning est un **frameset** : son URL ne contient aucune donnée,
   seulement des `<frame src=…>`. Les cadres sont donc suivis et c'est le
   document fils qui porte la grille horaire.

Le mot de passe universitaire ne sert qu'à l'appel de `login()` : il n'est ni
conservé en attribut, ni journalisé, ni écrit sur disque.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ── Constantes du portail ─────────────────────────────────────────────────────
HOME_URL = "https://siga.usm.cl/pag/home.jsp"
PLANNING_URL = "https://siga.usm.cl/pag/sistinsc/insc_horario_alumno_frameset.jsp"

# Domaines de messagerie proposés par le `<select name="server">` du formulaire.
SERVERS = [
    "usm.cl",
    "alumnos.usm.cl",
    "sansano.usm.cl",
    "titulados.usm.cl",
    "postgrado.usm.cl",
    "externos.usm.cl",
]

# Fuseau du campus ; surchargeable depuis l'interface pour un usage à distance.
DEFAULT_TIMEZONE = "America/Santiago"

# Suffixes d'hôtes autorisés pendant la navigation : le portail lui-même et la
# salle d'attente vers laquelle il redirige. Tout autre hôte interrompt la
# session — une redirection inattendue ne doit pas emporter les identifiants.
ALLOWED_HOST_SUFFIXES = (".usm.cl", ".queue-it.net")

# Sans session, le portail redirige vers `error_acceso.jsp` — marqueur observé
# sur une requête anonyme vers la page de planning.
_ACCESS_DENIED = "error_acceso"

# Après `valida_login.jsp`, SIGA n'émet pas de redirection HTTP : il renvoie une
# page portant un formulaire auto-soumis par JavaScript
# (`document.form_login.submit()`). En cas d'échec, ce formulaire pointe vers
# `error_ingreso_login.jsp`, dont la page affiche « Acceso no disponible ».
# Ces marqueurs proviennent d'une tentative réelle sur le portail, pas d'une
# supposition.
_LOGIN_ERROR_MARKERS = (
    "error_ingreso_login",
    "acceso no disponible",
    "clave incorrecta",
    "usuario o clave",
    "acceso denegado",
    _ACCESS_DENIED,
)

# Taille maximale d'un document récupéré sur le portail.
MAX_PAGE_BYTES = 4 * 1024 * 1024


# ── Grille horaire ────────────────────────────────────────────────────────────
# Repli utilisé uniquement quand l'en-tête de ligne annonce un numéro de module
# sans afficher d'horaire. Les blocs ainsi datés sont marqués `time_source =
# "module"` et signalés dans la prévisualisation : ces horaires sont indicatifs
# et demandent une vérification avant import.
MODULE_TIMES = {
    1: ("08:15", "09:25"),
    2: ("09:35", "10:45"),
    3: ("10:55", "12:05"),
    4: ("12:15", "13:25"),
    5: ("13:35", "14:45"),
    6: ("14:55", "16:05"),
    7: ("16:15", "17:25"),
    8: ("17:35", "18:45"),
    9: ("18:55", "20:05"),
    10: ("20:15", "21:25"),
}

# Jours en espagnol → indice ISO (lundi = 0), accents retirés au préalable.
_WEEKDAYS = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}

_WEEKDAY_LABELS = [
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
]

# `RRULE:FREQ=WEEKLY;BYDAY=…` attend les codes iCalendar, pas les indices.
_RRULE_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

_TIME_RE = re.compile(r"\b(\d{1,2})[:hH.](\d{2})\b")
_MODULE_RE = re.compile(r"\b(\d{1,2})\b")

# Chaque case de la grille de détail décrit son contenu dans l'appel JavaScript
# de son `onMouseOver` — jour, horaires, code, salle, tout y est explicite.
_CONSULTA_RE = re.compile(r"\bConsulta\s*\((.*?)\)\s*;", re.S)

# Libellé de module tel qu'il apparaît dans ces appels : « 7 (12:30-13.05) ».
# Le séparateur d'heure varie (deux-points ou point) — le portail est inconstant.
_MODULE_SLOT_RE = re.compile(r"^(\d{1,2})\s*\(\s*\d{1,2}[:h.]\d{2}\s*-\s*\d{1,2}[:h.]\d{2}\s*\)")

_TABLE_RE = re.compile(r"<table\b", re.I)

# Chemins de pages mentionnant « horario », relevés dans le HTML brut du menu :
# les destinations passées à des fonctions JavaScript échappent aux `<a href>`.
_HORARIO_PATH_RE = re.compile(r"[\w./~-]*horario[\w./~-]*\.jsp[\w?&=%.,+-]*", re.I)

# Le menu ne navigue pas : chaque entrée appelle
# `Enviar('page.jsp', v, menu, opcion, m, 'cible')`, qui remplit les champs
# cachés du formulaire `form` puis le poste. Ces cinq arguments font partie de
# la demande — sans eux, la page répond un corps blanc (voir CLAUDE.md).
_ENVIAR_RE = re.compile(
    r"Enviar\(\s*['\"]([^'\"]+\.jsp)['\"]\s*,\s*([^,]*),\s*([^,]*),\s*([^,]*),\s*([^,)]*)",
    re.I,
)

# Champs du formulaire `form` du menu, dans l'ordre des arguments de `Enviar()`.
_ENVIAR_FIELDS = ("v", "menu", "opcion", "m")

# Appel JavaScript de soumission — `document.form1.submit()`, éventuellement
# écrit `document.forms['form1'].submit()`. Le nom capturé désigne le formulaire
# à soumettre à la main, faute de moteur JavaScript.
_SUBMIT_CALL_RE = re.compile(
    r"document(?:\.forms)?[.\[]\s*['\"]?(\w+)['\"]?\s*\]?\s*\.submit\(\)"
)


class SigaError(Exception):
    """Échec fonctionnel du connecteur, destiné à être affiché à l'utilisateur."""


def _strip_function_bodies(script: str) -> str:
    """Retire le corps des fonctions d'un script.

    Un `document.form1.submit()` écrit dans une fonction n'est exécuté que sur
    une action de l'utilisateur ; seul un appel de premier niveau — ou un
    `onload` — part au chargement de la page. Confondre les deux fait soumettre
    des formulaires qu'un navigateur n'aurait jamais envoyés, et emmène la
    navigation au-delà de la page cherchée.
    """
    out, index = [], 0
    while True:
        start = script.find("function", index)
        if start < 0:
            out.append(script[index:])
            return "".join(out)
        out.append(script[index:start])
        brace = script.find("{", start)
        if brace < 0:
            return "".join(out)
        depth, pos = 1, brace + 1
        while pos < len(script) and depth:
            depth += {"{": 1, "}": -1}.get(script[pos], 0)
            pos += 1
        index = pos


def _has_grid(documents) -> bool:
    """Un des documents porte-t-il un tableau, donc une grille exploitable ?

    Sert de critère d'arrêt au repli par le menu : le frameset seul n'en a
    aucun, et une page utile en a toujours au moins un.
    """
    return any("<table" in (html or "").lower() for _, html in documents)


def _is_login_wall(url: str, html: str) -> bool:
    """Détecte une page « non connecté ».

    Deux signaux seulement, choisis pour leur précision : la redirection vers
    `error_acceso.jsp`, et la présence du formulaire de connexion lui-même. Un
    simple lien vers `valida_login.jsp` ne suffit pas — la page authentifiée
    peut en contenir un.
    """
    lowered = (html or "").lower()
    return (
        _ACCESS_DENIED in (url or "").lower()
        or _ACCESS_DENIED in lowered
        or ("valida_login.jsp" in lowered and 'name="passwd"' in lowered)
    )


# ── Utilitaires texte ─────────────────────────────────────────────────────────
def strip_accents(value: str) -> str:
    """Retire les diacritiques pour comparer « miércoles » et « miercoles »."""
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _normalize(value: str) -> str:
    """Forme canonique pour les comparaisons : sans accent, minuscules, compacte."""
    return re.sub(r"\s+", " ", strip_accents(value)).strip().lower()


def _clean_lines(value: str):
    """Découpe un texte de cellule en lignes utiles, espaces insécables compris."""
    value = value.replace("\xa0", " ")
    lines = []
    for raw in value.splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" -|·")
        if line:
            lines.append(line)
    return lines


# ── Client HTTP ───────────────────────────────────────────────────────────────
class SigaClient:
    """Session authentifiée sur SIGA, avec suivi manuel des redirections.

    Les redirections sont suivies à la main — et non par `allow_redirects=True` —
    pour revalider l'hôte à *chaque* saut : le portail rebondit vers Queue-it et
    revient, et seule une revalidation par saut garantit que les cookies de
    session ne partent pas vers un hôte tiers.
    """

    def __init__(self, timeout: int = 20, max_redirects: int = 10, url_guard=None):
        self.session = requests.Session()
        self.session.headers.update({
            # Le portail sert des pages différentes aux clients qu'il ne
            # reconnaît pas ; un User-Agent de navigateur évite ce chemin.
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "es-CL,es;q=0.9",
        })
        self.timeout = timeout
        self.max_redirects = max_redirects
        # Validation SSRF injectée par l'appelant (voir `_is_public_url` dans
        # app.py) : évite de dupliquer ici la logique de résolution DNS.
        self.url_guard = url_guard
        # Page d'arrivée de `login()`, renseignée après authentification.
        self.landing_url = ""
        self.landing_html = ""
        # Journal des réponses obtenues pendant `fetch_planning()`, repris par
        # /siga/diagnostic. Une page vide et une page inattendue produisent le
        # même résultat — zéro créneau — et seuls le code HTTP et la taille les
        # distinguent.
        self.transcript = []

    # ── Requêtes ──────────────────────────────────────────────────────────────
    def _check_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise SigaError(f"URL refusée : {url}")
        host = parsed.hostname.lower()
        if not any(host == suffix.lstrip(".") or host.endswith(suffix)
                   for suffix in ALLOWED_HOST_SUFFIXES):
            raise SigaError(
                f"Redirection vers un hôte inattendu ({host}) — session interrompue "
                "par précaution."
            )
        if self.url_guard and not self.url_guard(url):
            raise SigaError(f"URL refusée : seules les adresses publiques sont acceptées ({host}).")

    def request(self, method: str, url: str, data=None) -> requests.Response:
        """Exécute une requête en suivant les redirections, hôte revalidé à chaque saut."""
        for _ in range(self.max_redirects + 1):
            self._check_url(url)
            try:
                resp = self.session.request(
                    method, url, data=data, timeout=self.timeout,
                    allow_redirects=False, stream=True,
                )
            except requests.RequestException as exc:
                raise SigaError(f"Portail injoignable : {exc}") from exc

            if resp.is_redirect or resp.is_permanent_redirect:
                location = resp.headers.get("location")
                resp.close()
                if not location:
                    raise SigaError("Redirection sans destination.")
                url = urljoin(url, location)
                # 301/302/303 après un POST : le navigateur repasse en GET et
                # abandonne le corps. Reproduire ce comportement évite de
                # renvoyer le mot de passe vers l'étape suivante.
                if resp.status_code in (301, 302, 303):
                    method, data = "GET", None
                continue

            self._read_body(resp)
            return resp

        raise SigaError("Trop de redirections — la salle d'attente Queue-it boucle peut-être.")

    def _read_body(self, resp: requests.Response) -> None:
        """Charge le corps sous plafond et force le décodage en ISO-8859-1."""
        chunks, total = [], 0
        try:
            for chunk in resp.iter_content(65536):
                total += len(chunk)
                if total > MAX_PAGE_BYTES:
                    raise SigaError("Page anormalement volumineuse — abandon.")
                chunks.append(chunk)
        finally:
            resp.close()
        resp._content = b"".join(chunks)
        resp._content_consumed = True
        # Le portail déclare ISO-8859-1 ; quand l'en-tête manque (certains
        # cadres), requests retomberait sur UTF-8 et produirait du mojibake.
        if not resp.encoding or resp.encoding.lower() in ("utf-8", "iso-8859-1"):
            resp.encoding = "ISO-8859-1"

    def get(self, url: str) -> requests.Response:
        return self.request("GET", url)

    @staticmethod
    def _auto_submit_target(html: str):
        """Nom du formulaire que la page soumet d'elle-même au chargement.

        Deux formes acceptées : l'attribut `onload` du `<body>`, et un appel de
        premier niveau dans un `<script>`. À défaut, un `.submit()` isolé suffit
        encore sur une page ne portant **qu'un** formulaire — les pages relais de
        connexion en dépendent, et leur forme exacte n'est pas garantie ; au-delà
        d'un formulaire, deviner lequel soumettre ferait plus de mal que de bien.
        """
        soup = BeautifulSoup(html, "html.parser")
        body = soup.find("body")
        if body:
            match = _SUBMIT_CALL_RE.search(body.get("onload") or "")
            if match:
                return match.group(1)
        for script in soup.find_all("script"):
            match = _SUBMIT_CALL_RE.search(_strip_function_bodies(script.get_text()))
            if match:
                return match.group(1)
        if ".submit()" in html and len(soup.find_all("form")) == 1:
            return ""
        return None

    def _follow_auto_submit(self, resp: requests.Response, max_hops: int = 3,
                            collect=None):
        """Soumet les formulaires que le portail auto-soumet en JavaScript.

        SIGA enchaîne ses étapes avec des pages du type ::

            <form name="form_login" action="…" method="post"></form>
            <script>document.form_login.submit();</script>

        et remplit ses cadres de la même façon — `insc_horario_per_opc_alumno.jsp`
        poste `form1` depuis `onLoad` pour peupler le cadre voisin. `requests`
        n'exécutant aucun script, s'arrêter là laisserait la session à mi-chemin,
        rendrait indétectable un échec d'authentification, et laisserait la
        grille horaire vide.
        """
        for _ in range(max_hops):
            html = resp.text
            target = self._auto_submit_target(html)
            if target is None:
                return resp
            soup = BeautifulSoup(html, "html.parser")
            # Le formulaire visé est celui que le script nomme, pas simplement le
            # premier de la page : `menu.jsp` en empile une demi-douzaine.
            form = (soup.find("form", attrs={"name": target}) if target
                    else None) or soup.find("form")
            action = (form.get("action") or "").strip() if form else ""
            if not action:
                return resp
            data = {}
            for field_tag in form.find_all(["input", "select", "textarea"]):
                name = field_tag.get("name")
                if not name:
                    continue
                if field_tag.name == "select":
                    # Un `<select>` ne porte pas sa valeur : elle est sur l'option
                    # sélectionnée. Sans cette lecture, `periodo` partirait vide et
                    # la grille reviendrait blanche.
                    options = field_tag.find_all("option")
                    chosen = next((o for o in options if o.has_attr("selected")),
                                  options[0] if options else None)
                    if chosen is not None:
                        data[name] = chosen.get("value", chosen.get_text(strip=True))
                    continue
                kind = (field_tag.get("type") or "").lower()
                # Une case non cochée n'est pas transmise par un navigateur.
                if kind in ("radio", "checkbox") and not field_tag.has_attr("checked"):
                    continue
                data[name] = field_tag.get("value") or ""
            # Le formulaire de connexion ne se rejoue jamais à l'aveugle : ses
            # champs sortiraient vides de cette lecture, et le portail répondrait
            # « Acceso no disponible » — un échec d'authentification fabriqué de
            # toutes pièces, qui peut au passage invalider la session en cours.
            if any(f.get("type", "").lower() == "password"
                   for f in form.find_all("input")) or "passwd" in data:
                return resp
            method = "POST" if (form.get("method") or "get").lower() == "post" else "GET"
            resp = self.request(method, urljoin(resp.url, action), data=data or None)
            # Chaque étape est offerte à l'appelant : la page cherchée peut être
            # une escale, et non la dernière du parcours.
            if collect is not None:
                collect.append(resp)
        return resp

    # ── Authentification ──────────────────────────────────────────────────────
    def login(self, login: str, password: str, server: str = "usm.cl") -> None:
        """Ouvre une session sur le portail.

        `login` accepte aussi bien « nombre.apellido » que l'adresse complète,
        auquel cas le domaine saisi l'emporte sur `server`.
        """
        login = (login or "").strip()
        password = password or ""
        if not login or not password:
            raise SigaError("Identifiant et mot de passe sont obligatoires.")

        if "@" in login:
            login, _, server = login.partition("@")
            login, server = login.strip(), server.strip()
        if server not in SERVERS:
            raise SigaError(
                f"Domaine « {server} » inconnu. Valeurs acceptées : {', '.join(SERVERS)}."
            )

        # Première visite : dépose JSESSIONID et franchit la salle d'attente.
        self.get(HOME_URL)

        resp = self.request(
            "POST",
            urljoin(HOME_URL, "valida_login.jsp"),
            data={"login": login, "server": server, "passwd": password},
        )
        resp = self._follow_auto_submit(resp)

        # Le portail répond 200 même en cas d'échec : le verdict se lit dans
        # l'URL d'arrivée et dans le texte de la page, pas dans le code HTTP.
        haystack = _normalize(resp.url) + " " + _normalize(resp.text)
        if any(marker in haystack for marker in _LOGIN_ERROR_MARKERS):
            raise SigaError(
                "Connexion refusée par SIGA — identifiant, domaine ou mot de passe "
                "incorrect. Vérifiez aussi le domaine choisi "
                "(@usm.cl, @alumnos.usm.cl, @sansano.usm.cl…)."
            )

        # Page d'arrivée après authentification : c'est elle qui porte le menu de
        # l'étudiant. `HOME_URL` n'est que le formulaire de connexion et ne
        # convient donc pas pour chercher un lien vers le planning.
        self.landing_url = resp.url
        self.landing_html = resp.text

    def _note(self, resp: requests.Response) -> None:
        """Consigne une réponse dans le journal de diagnostic."""
        self.transcript.append({
            "url": resp.url,
            "statut": resp.status_code,
            "octets": len(resp.content or b""),
            "type": resp.headers.get("Content-Type", ""),
        })

    def _fetch_with_frames(self, url: str, documents: list, depth: int = 1,
                           method: str = "GET", data=None) -> None:
        """Ajoute une page et le contenu de ses cadres à `documents`."""
        try:
            resp = self.request(method, url, data=data)
        except SigaError:
            # Un cadre décoratif (bandeau, menu) peut échouer sans que le
            # planning soit perdu : on continue avec les autres.
            return
        self._note(resp)
        documents.append((resp.url, resp.text))

        # Un cadre ne porte pas toujours son contenu : `opc_alumno` poste `form1`
        # depuis `onLoad`, et c'est cette réponse-là qui contient la grille.
        # Toutes les étapes sont conservées, pas seulement la dernière : le
        # parcours peut dépasser la page cherchée et finir sur le pied de page.
        chain = []
        try:
            self._follow_auto_submit(resp, collect=chain)
        except SigaError:
            pass
        for step in chain:
            self._note(step)
            documents.append((step.url, step.text))

        if depth <= 0:
            return
        for frame_url in self._frame_urls(resp.text, resp.url):
            self._fetch_with_frames(frame_url, documents, depth - 1)

    def fetch_planning(self, url: str = PLANNING_URL):
        """Récupère la page de planning et le contenu de ses cadres.

        Renvoie une liste de couples `(url, html)` : le frameset lui-même puis
        chaque cadre résolu, dans l'ordre de découverte.
        """
        self.transcript = []
        resp = self._follow_auto_submit(self.get(url))
        final_url = resp.url
        html = resp.text
        self._note(resp)

        if _is_login_wall(final_url, html):
            raise SigaError(
                "SIGA a renvoyé la page de connexion : la session n'est pas ouverte "
                "ou a expiré. Réessayez."
            )

        documents = [(final_url, html)]
        for frame_url in self._frame_urls(html, final_url):
            # Un seul niveau d'imbrication supplémentaire : les framesets SIGA
            # ne vont pas plus loin, et cela borne le nombre de requêtes.
            self._fetch_with_frames(frame_url, documents, depth=1)

        # Repli : l'URL de planning en dur peut répondre une page vide, ou un
        # frameset sans cadre, selon le chemin emprunté dans le portail. On
        # refait alors le trajet d'un étudiant — passer par le menu — plutôt que
        # de rendre une extraction vide.
        if not _has_grid(documents):
            actions, menu_pages = self._discover_planning_actions(exclude=final_url)
            # Les pages de menu rejoignent le diagnostic : quand la découverte
            # échoue, c'est là que se lit ce que le portail propose réellement.
            documents.extend(menu_pages)
            for action in actions:
                self._fetch_with_frames(action["url"], documents, depth=1,
                                        method=action["method"], data=action.get("data"))
                if _has_grid(documents):
                    break

        return documents

    def _discover_planning_actions(self, exclude: str = "", limit: int = 5):
        """Cherche dans le menu de l'étudiant de quoi atteindre le planning.

        Le résultat n'est pas une liste d'URL mais de requêtes : le menu SIGA
        poste un formulaire (`Enviar()`) au lieu de naviguer, et la page de
        planning renvoie un corps blanc si elle est demandée sans ces
        paramètres. Les liens ordinaires restent traités en GET, après.

        Le point de départ est la page d'arrivée de `login()`, jamais `HOME_URL` —
        cette dernière porte le formulaire de connexion et non le menu.

        Les liens sont relevés à la fois dans les `<a href>` et dans le HTML
        brut : le menu SIGA passe une partie de ses destinations à des fonctions
        JavaScript (`abre('…jsp')`), invisibles d'une lecture des seules ancres.

        Renvoie `(candidats, pages_de_menu)`.
        """
        pages = []
        if self.landing_html:
            pages.append((self.landing_url, self.landing_html))
        else:
            try:
                home = self._follow_auto_submit(self.get(HOME_URL))
            except SigaError:
                return [], []
            self._note(home)
            pages.append((home.url, home.text))

        for frame_url in self._frame_urls(pages[0][1], pages[0][0]):
            try:
                frame = self.get(frame_url)
            except SigaError:
                continue
            self._note(frame)
            pages.append((frame.url, frame.text))
            # Le menu vit souvent dans un cadre imbriqué du frameset d'accueil.
            for nested_url in self._frame_urls(frame.text, frame.url):
                try:
                    nested = self.get(nested_url)
                except SigaError:
                    continue
                self._note(nested)
                pages.append((nested.url, nested.text))

        posts, gets, seen = [], [], set()
        for page_url, page_html in pages:
            # 1. Les entrées de menu, avec les paramètres que `Enviar()` poste.
            for match in _ENVIAR_RE.findall(page_html):
                path, args = match[0], match[1:]
                if "horario" not in _normalize(path):
                    continue
                data = {name: arg.strip().strip("'\"")
                        for name, arg in zip(_ENVIAR_FIELDS, args)}
                data["listado"] = ""
                resolved = urljoin(page_url, path)
                key = (resolved, tuple(sorted(data.items())))
                if key not in seen:
                    seen.add(key)
                    posts.append({"url": resolved, "method": "POST", "data": data})

            # 2. Les liens ordinaires, en repli — moins probables mais gratuits.
            soup = BeautifulSoup(page_html, "html.parser")
            hrefs = [(tag.get("href") or "").strip() for tag in soup.find_all("a")]
            for raw in hrefs + _HORARIO_PATH_RE.findall(page_html):
                if not raw or raw.lower().startswith(("javascript:", "#", "mailto:")):
                    continue
                if "horario" not in _normalize(raw):
                    continue
                resolved = urljoin(page_url, raw)
                if resolved != exclude and ("GET", resolved) not in seen:
                    seen.add(("GET", resolved))
                    gets.append({"url": resolved, "method": "GET"})

        return (posts + gets)[:limit], pages

    @staticmethod
    def _frame_urls(html: str, base_url: str):
        """Extrait les URL des `<frame>` / `<iframe>`, résolues et dédoublonnées."""
        soup = BeautifulSoup(html, "html.parser")
        urls, seen = [], set()
        for tag in soup.find_all(["frame", "iframe"]):
            src = (tag.get("src") or "").strip()
            if not src or src.lower().startswith(("javascript:", "about:", "data:")):
                continue
            resolved = urljoin(base_url, src)
            if resolved not in seen:
                seen.add(resolved)
                urls.append(resolved)
        return urls

    def close(self) -> None:
        self.session.close()


# ── Modèle ────────────────────────────────────────────────────────────────────
@dataclass
class ScheduleBlock:
    """Un créneau hebdomadaire du planning."""

    weekday: int                 # 0 = lundi
    start: str                   # "HH:MM"
    end: str                     # "HH:MM"
    summary: str
    location: str = ""
    teacher: str = ""
    paralelo: str = ""
    code: str = ""
    raw: str = ""                # texte brut de la cellule, pour traçabilité
    time_source: str = "grille"  # "grille" (horaires lus) ou "module" (repli)
    modules: list = field(default_factory=list)

    @property
    def weekday_label(self) -> str:
        return _WEEKDAY_LABELS[self.weekday]

    @property
    def needs_review(self) -> bool:
        return self.time_source == "module"

    def key(self) -> str:
        """Empreinte stable d'un créneau, base de l'`iCalUID`."""
        parts = [self.code or self.summary, self.paralelo,
                 str(self.weekday), self.start, self.end]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        data = self.__dict__.copy()
        data["weekday_label"] = self.weekday_label
        data["needs_review"] = self.needs_review
        data["key"] = self.key()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduleBlock":
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})


# ── Extraction de la grille ───────────────────────────────────────────────────
def _cell_text(cell) -> str:
    """Texte d'une cellule, `<br>` convertis en sauts de ligne."""
    for br in cell.find_all("br"):
        br.replace_with("\n")
    return cell.get_text("\n")


def _table_to_grid(table):
    """Développe un `<table>` en grille `(ligne, colonne) → texte`.

    `rowspan` et `colspan` sont matérialisés en dupliquant le contenu sur toutes
    les cases couvertes : un cours sur deux modules occupe alors deux lignes,
    que le regroupement ultérieur refusionnera. Sans cela, les cellules d'une
    même ligne se décalent et les cours changent de jour.
    """
    grid, rows, max_col = {}, 0, 0
    for row_index, tr in enumerate(table.find_all("tr")):
        col = 0
        for cell in tr.find_all(["td", "th"], recursive=False) or tr.find_all(["td", "th"]):
            while (row_index, col) in grid:
                col += 1
            try:
                rowspan = max(1, int(cell.get("rowspan", 1)))
                colspan = max(1, int(cell.get("colspan", 1)))
            except (TypeError, ValueError):
                rowspan = colspan = 1
            # Un rowspan aberrant (valeur fantaisiste) ferait exploser la grille.
            rowspan, colspan = min(rowspan, 30), min(colspan, 30)
            text = "\n".join(_clean_lines(_cell_text(cell)))
            for dr in range(rowspan):
                for dc in range(colspan):
                    grid[(row_index + dr, col + dc)] = text
            col += colspan
            max_col = max(max_col, col)
        rows = max(rows, row_index + 1)
    rows = max([r for (r, _) in grid], default=-1) + 1
    return grid, rows, max_col


def _find_day_axis(grid, rows, cols):
    """Localise l'axe des jours.

    Renvoie `(orientation, header_index, {index → jour})`. Les plannings SIGA
    placent habituellement les jours en colonnes, mais certaines vues les
    mettent en lignes ; les deux sont donc testées.

    Deux jours distincts suffisent : les vues compactes n'affichent que les
    jours effectivement occupés, et un étudiant peut n'avoir cours que deux
    jours par semaine. Le tri des fausses tables est assuré plus loin par
    `_find_slot_column()`, qui exige de vrais créneaux horaires.
    """
    # Jours en colonnes : on cherche la ligne d'en-tête.
    for r in range(min(rows, 8)):
        found = {}
        for c in range(cols):
            day = _match_day(grid.get((r, c), ""))
            if day is not None and day not in found.values():
                found[c] = day
        if len(found) >= 2:
            return "columns", r, found

    # Jours en lignes : on cherche la colonne d'en-tête.
    for c in range(min(cols, 4)):
        found = {}
        for r in range(rows):
            day = _match_day(grid.get((r, c), ""))
            if day is not None and day not in found.values():
                found[r] = day
        if len(found) >= 2:
            return "rows", c, found

    return None, None, {}


def _match_day(text: str):
    """Reconnaît un nom de jour espagnol, éventuellement abrégé."""
    normalized = _normalize(text)
    if not normalized or len(normalized) > 20:
        return None
    for name, index in _WEEKDAYS.items():
        if normalized.startswith(name[:3]) and normalized[:len(name)] in name:
            return index
        if name in normalized:
            return index
    return None


def _parse_slot(label: str):
    """Déduit `(début, fin, source, modules)` de l'en-tête d'une ligne."""
    times = _TIME_RE.findall(label or "")
    if len(times) >= 2:
        start = f"{int(times[0][0]):02d}:{times[0][1]}"
        end = f"{int(times[-1][0]):02d}:{times[-1][1]}"
        if start != end:
            return start, end, "grille", _modules_in(label)

    # Pas d'horaire affiché : repli sur la table des modules.
    modules = _modules_in(label)
    known = [m for m in modules if m in MODULE_TIMES]
    if known:
        return (MODULE_TIMES[known[0]][0], MODULE_TIMES[known[-1]][1],
                "module", known)

    return None, None, None, []


def _modules_in(label: str):
    """Numéros de module cités dans un en-tête (« Módulo 3-4 » → [3, 4])."""
    normalized = _normalize(label or "")
    # Les horaires contiennent aussi des chiffres : on les neutralise d'abord.
    normalized = _TIME_RE.sub(" ", normalized)
    return [int(n) for n in _MODULE_RE.findall(normalized) if 1 <= int(n) <= 14]


def _looks_like_schedule(grid, rows, cols) -> bool:
    """Pré-filtre bon marché : écarte les tables sans axe des jours."""
    _, _, days = _find_day_axis(grid, rows, cols)
    return len(days) >= 2


def _split_js_args(text: str):
    """Découpe la liste d'arguments d'un appel JavaScript.

    Un simple `split(",")` ne suffit pas : les libellés du portail contiennent
    des virgules (« ROMINGER CAMILLE, MARIE »). Les guillemets sont retirés, les
    identifiants nus comme `this` conservés tels quels.
    """
    args, current, quote, index = [], [], None, 0
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\" and index + 1 < len(text):
                current.append(text[index + 1])
                index += 2
                continue
            if char == quote:
                quote = None
            else:
                current.append(char)
        elif char in "'\"":
            quote = char
        elif char == ",":
            args.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    args.append("".join(current).strip())
    return args


def _blocks_from_consulta(html: str):
    """Lit les créneaux dans les appels `Consulta(...)` des cellules.

    C'est la source de vérité de la page de détail : chaque case de la grille
    porte un `onMouseOver="Consulta(sede, jornada, jour, 'N (HH:MM-HH:MM)',
    'CODE - NOM', paralelo, professeur, type, this, salle, état)"`. Tout y est
    explicite — inutile de déduire le jour d'une position en colonne ni l'heure
    d'un numéro de module.

    Le portail découpe la journée en modules d'environ 35 minutes et répète la
    même case sur chacun : les modules consécutifs d'un même cours sont donc
    refusionnés en un seul créneau.
    """
    found = []
    for match in _CONSULTA_RE.finditer(html):
        args = _split_js_args(match.group(1))
        # Le jour et le module sont repérés par leur forme, pas par leur rang :
        # seul l'ordre *après* le module est supposé stable.
        day_index = next((i for i, a in enumerate(args) if _match_day(a) is not None), None)
        slot_index = next((i for i, a in enumerate(args)
                           if _MODULE_SLOT_RE.match(a.strip())), None)
        if day_index is None or slot_index is None:
            continue
        weekday = _match_day(args[day_index])
        slot = _MODULE_SLOT_RE.match(args[slot_index].strip())
        times = _TIME_RE.findall(args[slot_index])
        if weekday is None or len(times) < 2:
            continue

        def arg(offset, default=""):
            position = slot_index + offset
            return args[position].strip() if position < len(args) else default

        course = arg(1)
        code, _, name = course.partition(" - ")
        found.append({
            "weekday": weekday,
            "module": int(slot.group(1)),
            "start": f"{int(times[0][0]):02d}:{times[0][1]}",
            "end": f"{int(times[1][0]):02d}:{times[1][1]}",
            "code": code.strip(),
            "name": " ".join(name.split()) or code.strip(),
            "paralelo": arg(2),
            "teacher": " ".join(arg(3).split()),
            "kind": arg(4),
            "room": arg(6),
            "status": arg(7),
            "context": " — ".join(a for a in args[:day_index] if a),
        })

    # Regroupement : même cours, même jour, même salle → modules consécutifs
    # fusionnés en un créneau unique.
    blocks, groups = [], {}
    for item in found:
        signature = (item["weekday"], item["code"], item["name"], item["paralelo"],
                     item["kind"], item["room"], item["teacher"])
        groups.setdefault(signature, []).append(item)

    for signature, items in groups.items():
        items.sort(key=lambda i: i["module"])
        run = [items[0]]
        for item in items[1:]:
            if item["module"] == run[-1]["module"] + 1:
                run.append(item)
            else:
                blocks.append(_block_from_run(run))
                run = [item]
        blocks.append(_block_from_run(run))

    blocks.sort(key=lambda b: (b.weekday, b.start))
    return blocks


def _block_from_run(run):
    """Assemble un créneau à partir de modules consécutifs d'un même cours."""
    first, last = run[0], run[-1]
    modules = [item["module"] for item in run]
    summary = first["name"]
    if first["kind"]:
        # Cátedra et Ayudantía d'une même matière portent sinon le même titre.
        summary = f"{summary} — {first['kind']}"
    details = [first["context"], f"Type : {first['kind']}" if first["kind"] else "",
               f"Statut : {first['status']}" if first["status"] else "",
               f"Modules {modules[0]}-{modules[-1]}" if len(modules) > 1
               else f"Module {modules[0]}"]
    return ScheduleBlock(
        weekday=first["weekday"],
        start=first["start"],
        end=last["end"],
        summary=summary,
        location=first["room"],
        teacher=first["teacher"],
        paralelo=first["paralelo"],
        code=first["code"],
        raw=" | ".join(d for d in details if d),
        time_source="grille",
        modules=modules,
    )


def parse_horario(documents):
    """Extrait les créneaux du planning.

    `documents` est la liste `(url, html)` renvoyée par `fetch_planning()`.
    Renvoie `(blocs, diagnostic)` ; `diagnostic` décrit ce qui a été inspecté,
    de quoi comprendre un résultat vide sans relancer une session.

    Deux lectures, dans cet ordre : les appels `Consulta(...)` des cellules —
    exacts, c'est ainsi que le portail expose réellement le planning — puis, à
    défaut, l'analyse visuelle des tables, qui reste le seul recours si cette
    page change de forme.
    """
    diagnostic = {"documents": [], "tables_inspectees": 0, "table_retenue": None}
    best = None

    for url, html in documents:
        blocks = _blocks_from_consulta(html)
        if blocks and (best is None or len(blocks) > len(best[0])):
            best = (blocks, {"url": url, "source": "Consulta()"})
    if best is not None:
        diagnostic["documents"] = [{"url": u, "tables": len(_TABLE_RE.findall(h))}
                                   for u, h in documents]
        diagnostic["table_retenue"] = best[1]
        return best[0], diagnostic

    for url, html in documents:
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        diagnostic["documents"].append({"url": url, "tables": len(tables)})
        for index, table in enumerate(tables):
            diagnostic["tables_inspectees"] += 1
            grid, rows, cols = _table_to_grid(table)
            if rows < 2 or cols < 2 or not _looks_like_schedule(grid, rows, cols):
                continue
            blocks = _blocks_from_grid(grid, rows, cols)
            # Plusieurs tables peuvent ressembler à un planning (grille
            # imbriquée dans une table de mise en page) : on garde la plus
            # fournie.
            if blocks and (best is None or len(blocks) > len(best[0])):
                best = (blocks, {"url": url, "index": index})

    if best is None:
        return [], diagnostic

    diagnostic["table_retenue"] = best[1]
    return best[0], diagnostic


def _blocks_from_grid(grid, rows, cols):
    """Convertit une grille développée en créneaux."""
    orientation, header, days = _find_day_axis(grid, rows, cols)
    if not days:
        return []

    if orientation == "rows":
        # Transposition : la suite ne raisonne qu'en « jours en colonnes ».
        grid = {(c, r): v for (r, c), v in grid.items()}
        rows, cols = cols, rows
        orientation, header, days = "columns", header, days

    # Colonne des horaires : la première qui ne porte pas un jour et dont les
    # cellules ressemblent à des créneaux.
    slot_col = _find_slot_column(grid, rows, cols, days, header)
    if slot_col is None:
        return []

    # Créneau horaire de chaque ligne.
    slots = {}
    for r in range(header + 1, rows):
        start, end, source, modules = _parse_slot(grid.get((r, slot_col), ""))
        if start:
            slots[r] = (start, end, source, modules)

    blocks = []
    for col, weekday in sorted(days.items()):
        # Regroupe les lignes consécutives portant le même contenu : couvre à la
        # fois le `rowspan` (dupliqué par `_table_to_grid`) et les plannings qui
        # répètent la cellule sur chaque module.
        run_text, run_rows = None, []
        for r in range(header + 1, rows):
            text = grid.get((r, col), "").strip()
            if text and r in slots and text == run_text:
                run_rows.append(r)
                continue
            if run_text and run_rows:
                block = _make_block(run_text, run_rows, slots, weekday)
                if block:
                    blocks.append(block)
            run_text, run_rows = (text, [r]) if (text and r in slots) else (None, [])
        if run_text and run_rows:
            block = _make_block(run_text, run_rows, slots, weekday)
            if block:
                blocks.append(block)

    blocks.sort(key=lambda b: (b.weekday, b.start))
    return blocks


def _find_slot_column(grid, rows, cols, days, header):
    """Choisit la colonne d'en-tête de ligne portant les horaires ou modules."""
    best, best_score = None, 0
    for c in range(cols):
        if c in days:
            continue
        score = sum(
            1 for r in range(header + 1, rows)
            if _parse_slot(grid.get((r, c), ""))[0]
        )
        if score > best_score:
            best, best_score = c, score
    return best if best_score >= 2 else None


def _make_block(text, run_rows, slots, weekday):
    """Assemble un créneau à partir du texte d'une cellule et des lignes couvertes."""
    first, last = slots[run_rows[0]], slots[run_rows[-1]]
    start, end = first[0], last[1]
    source = "module" if "module" in (first[2], last[2]) else "grille"
    modules = sorted({m for r in run_rows for m in slots[r][3]})

    lines = _clean_lines(text)
    if not lines:
        return None

    details = _parse_cell_details(lines)
    return ScheduleBlock(
        weekday=weekday,
        start=start,
        end=end,
        summary=details["summary"],
        location=details["location"],
        teacher=details["teacher"],
        paralelo=details["paralelo"],
        code=details["code"],
        raw=" | ".join(lines),
        time_source=source,
        modules=modules,
    )


def _parse_cell_details(lines):
    """Répartit les lignes d'une cellule entre intitulé, salle, paralelo, enseignant.

    Le format exact varie d'une vue à l'autre ; ce qui n'est pas reconnu reste
    disponible dans `raw`, repris intégralement dans la description de
    l'événement. Aucune information n'est donc perdue par un motif manqué.
    """
    details = {"summary": "", "location": "", "teacher": "", "paralelo": "", "code": ""}
    leftovers = []

    for line in lines:
        normalized = _normalize(line)
        value = line.split(":", 1)[1].strip() if ":" in line else line

        if normalized.startswith(("sala", "aula", "recinto")):
            details["location"] = value
        elif normalized.startswith(("prof", "docente")):
            details["teacher"] = value
        elif normalized.startswith(("paralelo", "par.")):
            details["paralelo"] = value
        else:
            leftovers.append(line)

    if leftovers:
        details["summary"] = leftovers[0]
        # Code d'asignatura type « MAT021 » ou « IWI-131 », éventuellement suivi
        # du paralelo (« MAT021-200 »).
        match = re.search(r"\b([A-Z]{2,4}[- ]?\d{2,4})\b", leftovers[0])
        if match:
            details["code"] = match.group(1)
        tail = " ".join(leftovers[1:])
        if tail and not details["location"]:
            # Certaines vues n'étiquettent pas la salle : « A-201 » seul.
            room = re.search(r"\b([A-Z]?\d{1,3}[-\s]?[A-Z]?\d{0,3})\b", tail)
            if room and len(tail) <= 30:
                details["location"] = tail.strip()
        if tail and details["location"] != tail.strip():
            details["summary"] = f"{details['summary']} — {tail}".strip(" —")

    if not details["summary"]:
        details["summary"] = lines[0]
    return details


# ── Conversion vers Google Calendar ───────────────────────────────────────────
def _first_occurrence(start_date: date, weekday: int) -> date:
    """Première date ≥ `start_date` tombant le jour voulu."""
    return start_date + timedelta(days=(weekday - start_date.weekday()) % 7)


def block_to_google_event(block: ScheduleBlock, start_date: date, end_date: date,
                          timezone: str = DEFAULT_TIMEZONE, term: str = ""):
    """Convertit un créneau en événement Google récurrent, ou `None` s'il sort de la période.

    L'heure est envoyée en **heure locale accompagnée de `timeZone`**, et non en
    instant UTC : une récurrence hebdomadaire doit suivre les changements
    d'heure du Chili, ce qu'un `dateTime` en `Z` figerait au décalage du premier
    jour.
    """
    first = _first_occurrence(start_date, block.weekday)
    if first > end_date:
        return None

    start_h, start_m = (int(p) for p in block.start.split(":"))
    end_h, end_m = (int(p) for p in block.end.split(":"))
    start_dt = datetime.combine(first, time(start_h, start_m))
    end_dt = datetime.combine(first, time(end_h, end_m))
    if end_dt <= start_dt:
        # Créneau franchissant minuit ou horaires inversés : une heure par défaut
        # vaut mieux qu'un événement rejeté par l'API.
        end_dt = start_dt + timedelta(hours=1)

    # `UNTIL` doit être un instant UTC. Un jour de marge absorbe le décalage
    # chilien (UTC-3/-4), sans risque d'ajouter une occurrence : le lendemain
    # tombe un autre jour de la semaine.
    until = datetime.combine(end_date + timedelta(days=1), time(23, 59, 59))
    rrule = (f"RRULE:FREQ=WEEKLY;BYDAY={_RRULE_DAYS[block.weekday]}"
             f";UNTIL={until.strftime('%Y%m%dT%H%M%SZ')}")

    description = _build_description(block, term)

    event = {
        "summary": block.summary,
        "description": description,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
        "recurrence": [rrule],
        # UID déterministe : réimporter le même planning met à jour les
        # événements existants au lieu de les dupliquer — c'est ce qui rend
        # l'opération synchronisable et non seulement importable.
        "iCalUID": f"siga-{block.key()}@siga.usm.cl",
        "extendedProperties": {
            "private": {
                "source": "siga",
                "sigaKey": block.key(),
                "sigaTerm": term or "",
            }
        },
        "reminders": {"useDefault": True},
    }
    if block.location:
        event["location"] = block.location
    return event


def _build_description(block: ScheduleBlock, term: str) -> str:
    """Compose la description : tous les détails du créneau, plus la trace brute."""
    lines = []
    if block.code:
        lines.append(f"Code : {block.code}")
    if block.paralelo:
        lines.append(f"Paralelo : {block.paralelo}")
    if block.location:
        lines.append(f"Salle : {block.location}")
    if block.teacher:
        lines.append(f"Enseignant : {block.teacher}")
    if block.modules:
        lines.append("Modules : " + "-".join(str(m) for m in block.modules))
    if term:
        lines.append(f"Période : {term}")
    if block.needs_review:
        lines.append(
            "⚠️ Horaire déduit du numéro de module (non affiché par SIGA) — à vérifier."
        )
    lines.append("")
    lines.append(f"Source SIGA : {block.raw}")
    lines.append(f"Importé le {date.today().isoformat()} depuis siga.usm.cl")
    return "\n".join(lines)


def blocks_to_google_events(blocks, start_date, end_date,
                            timezone=DEFAULT_TIMEZONE, term=""):
    """Convertit une liste de créneaux, en ignorant ceux hors période."""
    events = []
    for block in blocks:
        event = block_to_google_event(block, start_date, end_date, timezone, term)
        if event:
            events.append((block, event))
    return events
