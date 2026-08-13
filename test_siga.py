# -*- coding: utf-8 -*-
"""Tests du parseur SIGA — `python test_siga.py`, sans dépendance de test.

Les grilles ci-dessous reconstituent les formes rencontrées sur la page
« Horario del alumno » : `rowspan`, cellule répétée sur plusieurs modules,
grille transposée, horaires absents. Elles servent de garde-fou aux heuristiques
de [siga.py](siga.py), qui sont le point faible de la fonctionnalité — la page
réelle n'est pas consultable sans compte étudiant, et sa structure exacte n'a
donc jamais pu être observée.

Aucun accès réseau : tout se joue sur du HTML reconstitué.
"""

import sys
from datetime import date

import siga

failures = []


def check(label, condition, detail=""):
    if not condition:
        failures.append(label)
    print(f"[{'OK  ' if condition else 'FAIL'}] {label}"
          f"{('  -> ' + str(detail)) if detail and not condition else ''}")


# ── Cas 1 : jours en colonnes, horaires affichés, rowspan ─────────────────────
GRID = """
<html><body>
<table><tr><td>
  <table border="1">
    <tr>
      <th>M&oacute;dulo</th><th>Lunes</th><th>Martes</th>
      <th>Mi&eacute;rcoles</th><th>Jueves</th><th>Viernes</th>
    </tr>
    <tr>
      <td>1<br>08:15 - 09:25</td>
      <td rowspan="2">MAT021-200<br>Sala: A-201<br>Prof: J. P&eacute;rez</td>
      <td>&nbsp;</td><td>&nbsp;</td>
      <td rowspan="2">FIS110-201<br>Sala: B-105</td>
      <td>&nbsp;</td>
    </tr>
    <tr>
      <td>2<br>09:35 - 10:45</td>
      <td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td>
    </tr>
    <tr>
      <td>3<br>10:55 - 12:05</td>
      <td>&nbsp;</td>
      <td>IWI131-200<br>Sala: C-301<br>Paralelo: 200</td>
      <td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td>
    </tr>
  </table>
</td></tr></table>
</body></html>
"""

blocks, diag = siga.parse_horario([("http://x/h.jsp", GRID)])
check("cas 1 : 3 créneaux extraits", len(blocks) == 3, len(blocks))
by_day = {(b.weekday, b.start): b for b in blocks}

mat = by_day.get((0, "08:15"))
check("cas 1 : lundi 08:15 présent", mat is not None)
if mat:
    # rowspan=2 → le bloc couvre les modules 1 et 2, donc se termine à 10:45
    check("cas 1 : rowspan fusionné (fin 10:45)", mat.end == "10:45", mat.end)
    check("cas 1 : salle extraite", mat.location == "A-201", mat.location)
    check("cas 1 : enseignant extrait", mat.teacher == "J. Pérez", mat.teacher)
    check("cas 1 : code extrait", mat.code == "MAT021", mat.code)
    check("cas 1 : horaire lu, pas déduit", mat.time_source == "grille", mat.time_source)
    check("cas 1 : modules 1-2", mat.modules == [1, 2], mat.modules)

fis = by_day.get((3, "08:15"))
check("cas 1 : jeudi — l'accent de « miércoles » n'a pas décalé les colonnes",
      fis is not None and fis.summary.startswith("FIS110"),
      fis.summary if fis else None)

iwi = by_day.get((1, "10:55"))
check("cas 1 : mardi 10:55, paralelo lu", iwi is not None and iwi.paralelo == "200",
      iwi.paralelo if iwi else None)

# ── Cas 2 : cellule répétée sur chaque module, sans rowspan ───────────────────
REPEAT = """
<table>
  <tr><th>Hora</th><th>Lunes</th><th>Martes</th></tr>
  <tr><td>08:15 - 09:25</td><td>QUI100<br>Sala: D-1</td><td></td></tr>
  <tr><td>09:35 - 10:45</td><td>QUI100<br>Sala: D-1</td><td></td></tr>
  <tr><td>10:55 - 12:05</td><td></td><td>ELO101</td></tr>
</table>
"""
blocks2, _ = siga.parse_horario([("u", REPEAT)])
check("cas 2 : 2 créneaux (répétition fusionnée)", len(blocks2) == 2, len(blocks2))
qui = next((b for b in blocks2 if b.summary.startswith("QUI")), None)
check("cas 2 : fusion 08:15-10:45",
      qui is not None and (qui.start, qui.end) == ("08:15", "10:45"),
      (qui.start, qui.end) if qui else None)

# ── Cas 3 : jours en lignes (grille transposée) ───────────────────────────────
TRANSPOSED = """
<table>
  <tr><th>D&iacute;a</th><th>08:15 - 09:25</th><th>09:35 - 10:45</th></tr>
  <tr><td>Lunes</td><td>MAT021<br>Sala: A-1</td><td></td></tr>
  <tr><td>Martes</td><td></td><td>FIS110<br>Sala: B-2</td></tr>
  <tr><td>Mi&eacute;rcoles</td><td></td><td></td></tr>
</table>
"""
blocks3, _ = siga.parse_horario([("u", TRANSPOSED)])
check("cas 3 : 2 créneaux transposés", len(blocks3) == 2,
      [(b.weekday_label, b.start) for b in blocks3])
if len(blocks3) == 2:
    check("cas 3 : lundi 08:15", (blocks3[0].weekday, blocks3[0].start) == (0, "08:15"),
          (blocks3[0].weekday, blocks3[0].start))
    check("cas 3 : mardi 09:35", (blocks3[1].weekday, blocks3[1].start) == (1, "09:35"),
          (blocks3[1].weekday, blocks3[1].start))

# ── Cas 4 : repli sur la table des modules ────────────────────────────────────
MODULES = """
<table>
  <tr><th>M&oacute;dulo</th><th>Lunes</th><th>Martes</th><th>Jueves</th></tr>
  <tr><td>3</td><td>MAT023</td><td></td><td></td></tr>
  <tr><td>4</td><td>MAT023</td><td></td><td></td></tr>
</table>
"""
blocks4, _ = siga.parse_horario([("u", MODULES)])
check("cas 4 : 1 créneau", len(blocks4) == 1, len(blocks4))
if blocks4:
    b = blocks4[0]
    check("cas 4 : horaires déduits 10:55-13:25",
          (b.start, b.end) == ("10:55", "13:25"), (b.start, b.end))
    check("cas 4 : marqué « à vérifier »", b.needs_review is True, b.time_source)

# ── Cas 5 : table de mise en page ignorée ─────────────────────────────────────
LAYOUT = """
<table><tr><td>Bienvenido</td><td>Cerrar sesi&oacute;n</td></tr>
<tr><td>Men&uacute;</td><td>Inicio</td></tr></table>
"""
blocks5, _ = siga.parse_horario([("u", LAYOUT)])
check("cas 5 : aucune extraction sur une table de mise en page", blocks5 == [], blocks5)

# ── Cas 6 : ISO-8859-1 ────────────────────────────────────────────────────────
latin = "<table><tr><th>Día</th><th>Miércoles</th></tr>".encode("iso-8859-1")
check("cas 6 : accents préservés en latin-1", "Miércoles" in latin.decode("iso-8859-1"))
check("cas 6 : jour reconnu malgré l'accent", siga._match_day("Miércoles") == 2,
      siga._match_day("Miércoles"))

# ── Cas 7 : conversion Google Calendar ────────────────────────────────────────
start, end = date(2026, 8, 3), date(2026, 12, 11)   # un lundi → un vendredi
events = siga.blocks_to_google_events(blocks, start, end, "America/Santiago", "2026-2")
check("cas 7 : 3 événements générés", len(events) == 3, len(events))
block, ev = next((be for be in events if be[0].weekday == 0), (None, None))
check("cas 7 : première occurrence un lundi",
      ev and ev["start"]["dateTime"].startswith("2026-08-03T08:15"),
      ev["start"] if ev else None)
check("cas 7 : heure locale + timeZone (pas de suffixe Z, pour suivre l'heure d'été)",
      ev and not ev["start"]["dateTime"].endswith("Z")
      and ev["start"]["timeZone"] == "America/Santiago", ev["start"] if ev else None)
check("cas 7 : RRULE hebdomadaire bornée",
      ev and ev["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20261212T235959Z"],
      ev["recurrence"] if ev else None)
check("cas 7 : iCalUID présent", ev and ev["iCalUID"].startswith("siga-"),
      ev.get("iCalUID") if ev else None)
check("cas 7 : tous les détails dans la description",
      ev and "A-201" in ev["description"] and "J. Pérez" in ev["description"]
      and "Source SIGA" in ev["description"])
check("cas 7 : lieu renseigné", ev and ev.get("location") == "A-201",
      ev.get("location") if ev else None)

# UID stable d'une lecture à l'autre → synchronisation, et non duplication
again, _ = siga.parse_horario([("http://x/h.jsp", GRID)])
check("cas 7 : UID stable d'une extraction à l'autre",
      sorted(b.key() for b in blocks) == sorted(b.key() for b in again))
check("cas 7 : UID distincts entre créneaux",
      len({b.key() for b in blocks}) == len(blocks))

# ── Cas 8 : bornes de période ─────────────────────────────────────────────────
short = siga.blocks_to_google_events(blocks, date(2026, 8, 4), date(2026, 8, 5), "UTC")
check("cas 8 : créneaux hors période écartés",
      all(b.weekday in (1, 2) for b, _ in short), [b.weekday for b, _ in short])

# ── Cas 9 : détection du mur de connexion ─────────────────────────────────────
check("cas 9 : error_acceso détecté",
      siga._is_login_wall("https://siga.usm.cl/pag/error_acceso.jsp", ""))
check("cas 9 : formulaire de connexion détecté",
      siga._is_login_wall("https://siga.usm.cl/pag/home.jsp",
                          '<form action="valida_login.jsp"><input name="passwd"></form>'))
check("cas 9 : un simple lien vers valida_login.jsp ne vaut pas déconnexion",
      not siga._is_login_wall("https://siga.usm.cl/pag/x.jsp",
                              '<a href="valida_login.jsp">salir</a>'))

# ── Cas 10 : garde-fou sur les hôtes ──────────────────────────────────────────
client = siga.SigaClient()
try:
    client._check_url("https://evil.example.com/steal")
    check("cas 10 : hôte tiers refusé", False)
except siga.SigaError:
    check("cas 10 : hôte tiers refusé", True)
try:
    client._check_url("https://siga.usm.cl/pag/home.jsp")
    client._check_url("https://usm.queue-it.net/?c=usm")
    check("cas 10 : usm.cl et queue-it acceptés", True)
except siga.SigaError as e:
    check("cas 10 : usm.cl et queue-it acceptés", False, e)

# ── Cas 11 : repli par le menu quand le frameset est vide ─────────────────────
# Situation observée sur le portail : l'URL de planning en dur répond 200 avec un
# corps vide. Sans cadre ni tableau, l'extraction sortait zéro créneau sans rien
# expliquer. Le repli refait le trajet par le menu.
class _FakeResponse:
    def __init__(self, url, text):
        self.url = url
        self.text = text
        self.content = text.encode("latin-1")
        self.status_code = 200
        self.headers = {"Content-Type": "text/html"}


# Le menu réel de SIGA, réduit à l'essentiel : aucune entrée ne navigue, chacune
# remplit les champs cachés du formulaire `form` puis le poste via `Enviar()`.
MENU = (
    '<html><body>'
    "<a href=\"javascript:Enviar('sistinsc/insc_horario_alumno_frameset.jsp',"
    "0,0,0,0,'_parent')\" class=\"menu\">Horario personal</a>"
    '<a href="notas.jsp">Notas</a>'
    '<form name="form" method="post" action="" target="">'
    '<input type="hidden" name="v"><input type="hidden" name="menu">'
    '<input type="hidden" name="opcion"><input type="hidden" name="m">'
    '<input type="hidden" name="listado"></form>'
    '</body></html>'
)
LANDING_URL = "https://siga.usm.cl/pag/sistemas.jsp"
MENU_URL = "https://siga.usm.cl/pag/menu.jsp"
INNER_URL = "https://siga.usm.cl/pag/sistinsc/insc_horario_alumno.jsp"
PAGES = {
    # La page demandée en GET renvoie 6 octets de blanc — comportement observé.
    ("GET", siga.PLANNING_URL): "   \r\n",
    ("POST", siga.PLANNING_URL): '<frameset><frame src="insc_horario_alumno.jsp"></frameset>',
    ("GET", LANDING_URL): '<frameset><frame src="menu.jsp"></frameset>',
    ("GET", MENU_URL): MENU,
    ("GET", INNER_URL): GRID,
}

client = siga.SigaClient()
requested = []


def _fake_request(method, url, data=None):
    requested.append((method, url, data))
    if (method, url) not in PAGES:
        raise siga.SigaError(f"404 {method} {url}")
    return _FakeResponse(url, PAGES[(method, url)])


client.request = _fake_request
# État laissé par `login()` : c'est de cette page que part la recherche du menu.
client.landing_url = LANDING_URL
client.landing_html = PAGES[("GET", LANDING_URL)]
documents = client.fetch_planning()

check("cas 11 : le menu a été consulté après la page blanche",
      ("GET", MENU_URL, None) in requested, requested)
check("cas 11 : HOME_URL — la page de connexion — n'est jamais le point de départ",
      not any(url == siga.HOME_URL for _, url, _ in requested), requested)
check("cas 11 : l'entrée de menu est postée avec ses paramètres, pas ouverte en GET",
      ("POST", siga.PLANNING_URL,
       {"v": "0", "menu": "0", "opcion": "0", "m": "0", "listado": ""}) in requested,
      requested)
check("cas 11 : le cadre du frameset ainsi obtenu est suivi",
      ("GET", INNER_URL, None) in requested, requested)
blocks, _ = siga.parse_horario(documents)
check("cas 11 : la grille est retrouvée là où le GET direct ne donnait rien",
      len(blocks) == 3, len(blocks))
check("cas 11 : le journal note la taille de chaque réponse",
      any(e["url"] == siga.PLANNING_URL and e["octets"] == 5 for e in client.transcript),
      client.transcript)
check("cas 11 : les pages de menu rejoignent le diagnostic",
      any(url == MENU_URL for url, _ in documents), [u for u, _ in documents])

# Pas de requêtes superflues quand l'URL directe suffit.
requested.clear()
client.transcript = []
PAGES[("GET", siga.PLANNING_URL)] = GRID
documents = client.fetch_planning()
check("cas 11 : pas de détour par le menu quand la page directe porte la grille",
      not any(url == MENU_URL for _, url, _ in requested), requested)

# ── Cas 12 : le formulaire de connexion ne se rejoue jamais ───────────────────
# Régression observée : partir de `HOME_URL` faisait re-soumettre `form_login`
# avec des champs vides, donc fabriquer un « Acceso no disponible ».
login_page = (
    '<form name="form_login" action="valida_login.jsp" method="post">'
    '<input name="login" value=""><input type="password" name="passwd">'
    '</form><script>document.form_login.submit();</script>'
)
posted = []
client2 = siga.SigaClient()
client2.request = lambda method, url, data=None: posted.append(url)
check("cas 12 : la page de connexion n'est pas auto-soumise",
      client2._follow_auto_submit(_FakeResponse(siga.HOME_URL, login_page)) is not None
      and not posted, posted)

# Un formulaire relais ordinaire, lui, doit bien être soumis.
relay = ('<form name="f" action="next.jsp" method="post"><input name="id" value="7"></form>'
         '<script>document.f.submit();</script>')
posted.clear()
client2.request = lambda method, url, data=None: (
    posted.append(url) or _FakeResponse(url, "<html>ok</html>"))
client2._follow_auto_submit(_FakeResponse("https://siga.usm.cl/pag/x.jsp", relay))
check("cas 12 : un relais sans mot de passe reste suivi",
      posted == ["https://siga.usm.cl/pag/next.jsp"], posted)

# ── Cas 13 : un cadre qui poste son propre formulaire au chargement ───────────
# `insc_horario_per_opc_alumno.jsp` ne contient pas la grille : il poste `form1`
# depuis `onLoad`, avec la période choisie, et c'est la réponse qui la porte.
# Demandée en GET, la page de détail répond 4 octets.
OPC_URL = "https://siga.usm.cl/pag/sistinsc/insc_horario_per_opc_alumno.jsp?m=0&p_opcion=0"
DETALLE_URL = "https://siga.usm.cl/pag/sistinsc/insc_horario_per_detalle.jsp"
OPC = (
    '<html><body onLoad="document.form1.submit();">'
    '<form target="frame3" name="form1" method="post" action="insc_horario_per_detalle.jsp">'
    '<select name="periodo" class="Select">'
    '<option value="2025-1">2025 - 1</option>'
    '<option value="2026-2" selected>2026 - 2</option>'
    '</select>'
    '<input type="hidden" name="p_opcion" value="0">'
    '<input type="hidden" name="tipo_inscripcion" value="2">'
    '</form></body></html>'
)
PAGES3 = {("GET", OPC_URL): OPC, ("POST", DETALLE_URL): GRID}
sent = []


def _fake_request3(method, url, data=None):
    sent.append((method, url, data))
    if (method, url) not in PAGES3:
        raise siga.SigaError(f"404 {method} {url}")
    return _FakeResponse(url, PAGES3[(method, url)])


client3 = siga.SigaClient()
client3.request = _fake_request3
docs = []
client3._fetch_with_frames(OPC_URL, docs, depth=1)

posted_data = next((d for m, u, d in sent if m == "POST" and u == DETALLE_URL), None)
check("cas 13 : le formulaire du cadre est posté à la place du navigateur",
      posted_data is not None, sent)
check("cas 13 : la période vient de l'option sélectionnée, pas d'un champ vide",
      posted_data and posted_data.get("periodo") == "2026-2", posted_data)
check("cas 13 : les champs cachés accompagnent la demande",
      posted_data and posted_data.get("tipo_inscripcion") == "2"
      and posted_data.get("p_opcion") == "0", posted_data)
check("cas 13 : le formulaire et sa réponse sont tous deux conservés",
      len(docs) == 2 and docs[1][0] == DETALLE_URL, [u for u, _ in docs])
blocks, _ = siga.parse_horario(docs)
check("cas 13 : la grille est extraite de la réponse", len(blocks) == 3, len(blocks))

# ── Cas 14 : le parcours dépasse la grille ────────────────────────────────────
# Observé sur le portail : la page de détail elle-même repart vers le pied de
# page. Ne garder que la dernière réponse revenait à récupérer la grille puis à
# la jeter.
FOOTER_URL = "https://siga.usm.cl/pag/sistinsc/insc_horario_per_ultimo.jsp"
GRID_THEN_ONWARD = (
    GRID + '<form name="form2" method="post" action="insc_horario_per_ultimo.jsp"></form>'
    '<script>document.form2.submit();</script>'
)
PAGES4 = {
    ("GET", OPC_URL): OPC,
    ("POST", DETALLE_URL): GRID_THEN_ONWARD,
    ("POST", FOOTER_URL): "<html><body>Imprimir | Volver</body></html>",
}
client4 = siga.SigaClient()
client4.request = lambda method, url, data=None: (
    _FakeResponse(url, PAGES4[(method, url)]) if (method, url) in PAGES4
    else (_ for _ in ()).throw(siga.SigaError(f"404 {method} {url}")))
docs4 = []
client4._fetch_with_frames(OPC_URL, docs4, depth=1)

check("cas 14 : toutes les étapes sont conservées, pas seulement la dernière",
      [u for u, _ in docs4] == [OPC_URL, DETALLE_URL, FOOTER_URL], [u for u, _ in docs4])
blocks, _ = siga.parse_horario(docs4)
check("cas 14 : la grille survit au dépassement", len(blocks) == 3, len(blocks))

# Un `.submit()` enfermé dans une fonction n'est déclenché que par un clic.
dormant = (
    '<html><body><table><tr><td>grille</td></tr></table>'
    '<form name="f" action="ailleurs.jsp" method="post"></form>'
    '<form name="g" action="autre.jsp" method="post"></form>'
    '<script>function Imprimir(){ document.f.submit(); }</script>'
    '</body></html>'
)
check("cas 14 : un submit enfermé dans une fonction n'est pas déclenché",
      siga.SigaClient._auto_submit_target(dormant) is None,
      siga.SigaClient._auto_submit_target(dormant))
check("cas 14 : un onload explicite l'est",
      siga.SigaClient._auto_submit_target(
          '<html><body onLoad="document.form1.submit();"><form name="form1"></form>'
          '</body></html>') == "form1")

# ── Cas 15 : lecture des appels Consulta() ────────────────────────────────────
# Forme réelle de `insc_horario_per_detalle.jsp` : chaque case porte ses données
# dans son `onMouseOver`. Les modules d'environ 35 minutes se suivent et doivent
# être refusionnés ; les cases « TOPE DE HORARIO » n'en sont pas.
DETALLE = """
<html><body>
<tr><td onMouseOver="Consulta('Casa Central Valparaíso','Diurna','Miércoles','1 (08:15-08:50)','ELI270 - FUNDAMENTOS DE ELECTROTECNIA   ','1','S. ZUMARAN','Cátedra',this, 'C232','Inscrita');" bgcolor="#FF9900">ELI270 - 1</td></tr>
<tr><td onMouseOver="Consulta('Casa Central Valparaíso','Diurna','Miércoles','2 (08:50-09:25)','ELI270 - FUNDAMENTOS DE ELECTROTECNIA   ','1','S. ZUMARAN','Cátedra',this, 'C232','Inscrita');" bgcolor="#FF9900"></td></tr>
<tr><td onMouseOver="Consulta('Casa Central Valparaíso','Diurna','Miércoles','7 (12:30-13.05)','IQA222 - TRANSFERENCIA DE CALOR   ','1','ORTIZ, ALEJANDRO','Cátedra',this, 'P412','Inscrita');" bgcolor="#FF9900">IQA222 - 1</td></tr>
<tr><td onMouseOver="Consulta('Casa Central Valparaíso','Diurna','Jueves','11 (16:05-16:40)','IQA222 - TRANSFERENCIA DE CALOR   ','1',' ','Ayudantía',this, 'P308','Inscrita');" bgcolor="#FF9900">IQA222 - 1</td></tr>
<tr><td onMouseOver="ConsultaTexto(this,'<br><b>TOPE DE HORARIO.</b>','#FF6600');" bgcolor="#FF6600">&nbsp;</td></tr>
</body></html>
"""
found = siga._blocks_from_consulta(DETALLE)
check("cas 15 : 3 créneaux (les deux modules du premier cours fusionnés)",
      len(found) == 3, [(b.weekday_label, b.start, b.end, b.code) for b in found])

eli = next((b for b in found if b.code == "ELI270"), None)
check("cas 15 : modules 1 et 2 fusionnés en 08:15-09:25",
      eli and eli.start == "08:15" and eli.end == "09:25",
      (eli.start, eli.end) if eli else None)
check("cas 15 : jour lu dans l'appel, accent compris",
      eli and eli.weekday == 2, eli.weekday if eli else None)
check("cas 15 : salle, enseignant et paralelo repris",
      eli and eli.location == "C232" and eli.teacher == "S. ZUMARAN"
      and eli.paralelo == "1", (eli.location, eli.teacher) if eli else None)
check("cas 15 : horaire lu, jamais déduit d'un numéro de module",
      eli and eli.time_source == "grille" and eli.needs_review is False)

catedra = next((b for b in found if b.code == "IQA222" and b.weekday == 2), None)
ayudantia = next((b for b in found if b.code == "IQA222" and b.weekday == 3), None)
check("cas 15 : le séparateur d'heure « 13.05 » est accepté",
      catedra and catedra.start == "12:30" and catedra.end == "13:05",
      (catedra.start, catedra.end) if catedra else None)
check("cas 15 : Cátedra et Ayudantía se distinguent dans le titre",
      catedra and ayudantia and catedra.summary != ayudantia.summary
      and "Ayudantía" in ayudantia.summary,
      (catedra.summary, ayudantia.summary) if catedra and ayudantia else None)
check("cas 15 : un nom d'enseignant à virgule reste entier",
      catedra and catedra.teacher == "ORTIZ, ALEJANDRO",
      catedra.teacher if catedra else None)
check("cas 15 : les UID des deux restent distincts",
      catedra and ayudantia and catedra.key() != ayudantia.key())

# Le chemin `Consulta()` prime sur l'analyse visuelle, sans la supprimer.
priority, diag = siga.parse_horario([("http://x/detalle.jsp", DETALLE)])
check("cas 15 : parse_horario retient la lecture Consulta()",
      len(priority) == 3 and diag["table_retenue"]["source"] == "Consulta()", diag)
fallback, _ = siga.parse_horario([("http://x/h.jsp", GRID)])
check("cas 15 : l'analyse des tables reste le recours quand Consulta() est absent",
      len(fallback) == 3, len(fallback))

print()
print(f"{len(failures)} échec(s)" if failures else "Tous les cas passent.")
for f in failures:
    print("  -", f)
sys.exit(1 if failures else 0)
