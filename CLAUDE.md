# CLAUDE.md

Documentation interne pour le développement de ce dépôt. Le [README.md](README.md) couvre
l'installation et l'usage côté utilisateur ; ce fichier couvre l'architecture et les pièges.

## Vue d'ensemble

Deux implémentations indépendantes du même besoin — importer un `.ics` dans Google Agenda —
cohabitent dans le dépôt. Elles ne partagent **aucun** code.

| | Version statique | Variante Flask |
|---|---|---|
| Point d'entrée | [index.html](index.html) | [app.py](app.py) |
| OAuth | Côté client (Google Identity Services, token implicite) | Côté serveur (`google-auth-oauthlib`, code flow) |
| Parsing ICS | `ical.js` dans le navigateur | `icalendar` (Python) |
| Déploiement | GitHub Pages | Local uniquement |
| Statut | **Principale** — c'est celle qui évolue | Antérieure, conservée mais moins complète |

Sauf demande explicite, les modifications fonctionnelles vont dans la **version statique**.
La variante Flask n'est pas maintenue en parallèle : ne pas dupliquer une fonctionnalité
dans les deux sans que ce soit demandé.

**Exception : la synchronisation du planning SIGA** ([siga.py](siga.py)) vit dans la variante
Flask, et ne peut pas en sortir. Elle exige une session HTTP authentifiée sur un domaine
tiers ; un navigateur ne peut ni lire la réponse de `siga.usm.cl` depuis une autre origine
(aucun en-tête CORS sur ce portail JSP), ni porter les cookies de session. C'est le seul
domaine où la variante Flask dépasse la version statique.

## Version statique

Aucune étape de build, aucun gestionnaire de paquets. Les scripts sont chargés en balises
`<script>` dans l'ordre et communiquent par des globales.

```
index.html
  └─ js/ical.min.js   → global ICAL      (ical.js 1.5.0, tierce, ne pas éditer)
  └─ js/parser.js     → global ICSParser
  └─ js/gcal.js       → global GCal
  └─ js/app.js        → init(), pas d'export
```

### `js/parser.js` — `ICSParser`

`parseICS(texte)` renvoie un tableau de `ParsedEvent`. Chaque `ParsedEvent` encapsule le
`VEVENT` brut et expose :

- `googleEvent` — le corps prêt pour l'API Calendar (`null` si la conversion a échoué)
- `isValid` / `error` — un `VEVENT` sans `DTSTART` est marqué invalide plutôt que rejeté,
  pour rester visible dans la prévisualisation
- des accesseurs d'affichage (`startDisplay`, `summary`, `isRecurring`, …) formatés en `fr-FR`

La `RRULE` est transmise telle quelle ; les `EXDATE` sont réécrites en forme iCalendar
(`20260810T120000Z`, ou `EXDATE;VALUE=DATE:` pour les dates seules) — l'ISO-8601 étendu
est refusé par Google.

Les fuseaux horaires demandent trois précautions, toutes trois nécessaires :

1. `parseICS()` enregistre les `VTIMEZONE` du fichier dans `ICAL.TimezoneService` **avant**
   toute lecture de date (les valeurs sont résolues au premier accès, et le service est
   remis à zéro à chaque parse pour ne pas mélanger deux fichiers). Sans cet enregistrement,
   un TZID inconnu d'ical.js est traité comme heure *flottante*, donc lu dans le fuseau du
   navigateur : l'événement est importé décalé, sans aucune erreur visible.
2. `normalizeTimeZone()` traduit les noms Windows (`GMT Standard Time`, émis par Exchange
   et Outlook) en identifiants IANA via la table `WINDOWS_TO_IANA`, et valide le reste avec
   `Intl.DateTimeFormat`. Un nom non résoluble n'est **pas** transmis : Google répond
   « Invalid time zone definition for start time » et rejette l'événement entier.
3. `toDate()` rattrape le cas d'un TZID valide sans `VTIMEZONE` correspondant, en appliquant
   le fuseau à la main (`Intl`, double passe pour les changements d'heure).

`dateTime` est toujours un instant absolu suffixé `Z` ; `timeZone` ne sert donc qu'à la
récurrence et à l'affichage, et peut être omis sans casser l'import.

### `js/gcal.js` — `GCal`

Wrapper REST sur `https://www.googleapis.com/calendar/v3`. Le token d'accès vit dans la
closure (`_accessToken`) et n'est **jamais** persisté — un rechargement déconnecte.

Points à connaître :

- `init()` appelle `onToken(null)` immédiatement après avoir créé le token client. Ce n'est
  pas une erreur : c'est le signal « initialisation terminée, affiche le bouton de connexion ».
  Le callback sert donc à la fois d'événement de fin d'init et de callback de token.
- `_friendlyError()` traduit les codes d'erreur GIS en messages français. **Ces messages
  mentionnent `localhost:8080` en dur** — si le port de développement change, les mettre à jour.
- `importEvent()` implémente les trois stratégies de doublon. La détection passe par
  `findByUID()`, qui avale silencieusement ses erreurs et renvoie `null` (un échec de
  recherche est traité comme « pas de doublon »).
- Un événement avec `iCalUID` est créé via `events/import`, sans UID via `events` (POST).
  La stratégie `duplicate` retire l'`iCalUID` avant l'insertion, sinon Google déduplique.

### `js/app.js`

État global dans `State`, références DOM paresseuses via `UI.*()`. Interface en trois étapes
(`step-1` source, `step-2` prévisualisation, `step-3` résultat) pilotées par `showStep()`.

Le fichier sélectionné est stocké sur `UI.fileInput()._file` (propriété ajoutée à l'élément),
pas dans `State` — pensez-y en cas de refactorisation.

L'IIFE `waitForGIS` en fin de fichier attend que `google.accounts.oauth2` soit disponible
(le script GIS est chargé en `async`), avec 100 tentatives espacées de 100 ms, soit 10 s.

## Variante Flask

`app.py` est un fichier unique, `templates/index.html` embarque son CSS et son JS.
`css/` et `js/` **ne sont pas** servis par Flask (pas de dossier `static/`).

Écarts fonctionnels assumés par rapport à la version statique :

- pas de prévisualisation ni de sélection : le formulaire poste, le serveur importe tout
- pas de stratégie de doublon exposée — `events().import_()` est utilisé dès qu'un UID existe
- `ics_component_to_google_event()` ne transmet **pas** la `RRULE` : les récurrences sont
  importées comme des événements simples
- le `timeZone` envoyé vient de `str(start_dt.tzinfo)`, qui n'est pas garanti d'être un nom
  IANA valide selon la source du fichier

`OAUTHLIB_INSECURE_TRANSPORT=1` est forcé au chargement du module : ne pas exposer cette
variante hors de la machine locale. Le serveur n'écoute donc que sur `127.0.0.1:5000`, et
le débogueur Werkzeug — qui offre une console d'exécution de code — reste désactivé sauf
`FLASK_DEBUG=1`.

Les jetons OAuth ne transitent **pas** par le cookie de session : les sessions Flask sont
signées mais non chiffrées, leur contenu est lisible par le navigateur. Le cookie ne porte
qu'un identifiant opaque (`sid`), et `_CREDENTIALS_STORE` garde les credentials en mémoire
du processus. Deux conséquences à ne pas perdre de vue en cas d'évolution : un redémarrage
déconnecte, et l'app suppose **un seul processus** (pas de workers Gunicorn). Idem pour
`SECRET_KEY`, désormais tirée au hasard si l'environnement ne la fournit pas.

`fetch_ics_url()` protège la récupération d'ICS distants contre les SSRF : schéma limité à
HTTP(S), résolution DNS puis rejet des adresses privées, loopback, link-local et réservées,
revalidation à **chaque** redirection (suivies à la main, `allow_redirects=False`), et
plafond `MAX_ICS_BYTES`. Subsiste une fenêtre de DNS rebinding — la résolution de contrôle
n'est pas celle qu'utilise `requests` — jugée acceptable pour un outil local.

## Connecteur SIGA — `siga.py`

Se connecte au portail `siga.usm.cl` (Universidad Técnica Federico Santa María), lit la page
*Horario del alumno* et convertit la grille en événements Google récurrents. Routes associées
dans [app.py](app.py) : `/siga/planning` (lecture), `/siga/import` (synchronisation),
`/siga/oublier`, `/siga/diagnostic`.

### Quatre comportements du portail à ne pas perdre de vue

Tous constatés sur le site, pas déduits d'une documentation :

1. **Queue-it.** Le portail est derrière une salle d'attente (`usm.queue-it.net`). La première
   visite enchaîne des redirections inter-domaines qui déposent un cookie `QueueITAccepted-…`.
   Sans cookie jar partagé, on boucle jusqu'au plafond de redirections. D'où la
   `requests.Session` unique, et `ALLOWED_HOST_SUFFIXES` qui admet `.queue-it.net`.
2. **ISO-8859-1.** Les pages sont servies en latin-1. Décodées en UTF-8, « miércoles » devient
   du mojibake et la détection des jours échoue silencieusement — le planning sort vide sans
   erreur. `_read_body()` force donc l'encodage.
3. **Formulaires auto-soumis en JavaScript.** `valida_login.jsp` ne redirige pas : il renvoie
   une page contenant `<form>` + `document.form_login.submit()`. `requests` n'exécutant aucun
   script, `_follow_auto_submit()` soumet ce formulaire à la main. Sans cela la session reste
   à mi-chemin **et l'échec d'authentification devient indétectable**.
4. **Échecs en HTTP 200.** Un mauvais mot de passe donne un 200 vers
   `servletlogin?pag=error_ingreso_login.jsp`, dont la page affiche « Acceso no disponible ».
   Le verdict se lit dans l'URL et le texte (`_LOGIN_ERROR_MARKERS`), jamais dans le code HTTP.
   Sans session, la page de planning part sur `error_acceso.jsp` (`_is_login_wall()`).
5. **Le planning s'obtient en POST, pas en GET.** Demandée en GET, même authentifié,
   `insc_horario_alumno_frameset.jsp` répond 200 `text/html` avec **6 octets** de blanc
   (constaté le 13/08/2026). Le menu réel — `menu.jsp`, cadre de `sistemas.jsp` — ne navigue
   pas : chaque entrée appelle

   ```html
   <a href="javascript:Enviar('sistinsc/insc_horario_alumno_frameset.jsp',0,0,0,0,'_parent')">
   ```

   et `Enviar(a,v,menu,opcion,m,target)` remplit les champs cachés du formulaire `form`
   (`v`, `menu`, `opcion`, `m`, `listado`) puis le poste vers `a`. Ces paramètres font partie
   de la demande. `_discover_planning_actions()` relit donc ces appels (`_ENVIAR_RE`) et
   rejoue le POST ; les `<a href>` ordinaires ne servent que de repli en GET. La découverte
   ne se déclenche que si aucun document ne porte de `<table>` (`_has_grid()`) : le chemin
   nominal ne coûte aucune requête supplémentaire.

6. **La grille est peuplée par un cadre voisin.** Le POST ouvre un frameset imbriqué dont
   `insc_horario_per_detalle.jsp` porte la grille — mais il répond 4 octets tant qu'on le
   demande en GET. C'est `insc_horario_per_opc_alumno.jsp`, le cadre au-dessus, qui le
   remplit : `<body onLoad="document.form1.submit()">` poste `form1` vers lui avec la période
   (`<select name="periodo">`, ici `2026-2`) et six champs cachés. `_fetch_with_frames()`
   applique donc `_follow_auto_submit()` à **chaque** cadre, et conserve les deux documents —
   le formulaire dit quels paramètres ont été retenus, la réponse porte les créneaux.

Deux règles que ce repli a imposées, et qu'il ne faut pas défaire :

- **Le point de départ est `landing_url`/`landing_html`**, la page où `login()` a abouti,
  jamais `HOME_URL` — cette dernière est le formulaire de connexion, pas le menu.
- **`_follow_auto_submit()` refuse tout formulaire portant un champ mot de passe.** Lu par
  BeautifulSoup, `form_login` sort avec des champs vides ; le re-soumettre fabrique un
  « Acceso no disponible » indiscernable d'un vrai échec, et peut invalider la session.
- **Il vise le formulaire que le script nomme** (`_SUBMIT_CALL_RE`), pas le premier de la
  page — `menu.jsp` en empile une demi-douzaine — et lit la valeur d'un `<select>` sur son
  option sélectionnée, sans quoi `periodo` partirait vide et la grille reviendrait blanche.
  Un `.submit()` enfermé dans une fonction n'est *pas* déclenché (`_strip_function_bodies()`) :
  seul un `onload` ou un appel de premier niveau part au chargement.
- **Toutes les étapes du parcours sont conservées**, pas seulement la dernière. La page de
  détail repart d'elle-même vers le pied de page : ne garder que l'arrivée revenait à
  récupérer la grille puis à la jeter — extraction vide, sans trace de la cause.

`SigaClient.transcript` journalise URL, code HTTP, taille et type de chaque réponse de
`fetch_planning()` ; `diagnostic["arrivee_apres_login"]` donne `landing_url`. `/siga/diagnostic`
affiche les deux, et signale explicitement un corps vide. Sans cela, une page blanche et une
page inattendue sont indiscernables — les deux donnent zéro créneau.

### Extraction de la grille

`parse_horario()` reçoit la liste `(url, html)` de `fetch_planning()` — le frameset **et** ses
cadres, puisque l'URL du planning ne contient aucune donnée. Elle tente **deux lectures**,
dans cet ordre.

#### 1. Les appels `Consulta()` — la source de vérité

C'est ainsi que `insc_horario_per_detalle.jsp` expose réellement le planning : chaque case
de la grille décrit son contenu dans son propre `onMouseOver`.

```html
<td onMouseOver="Consulta('Casa Central Valparaíso','Diurna','Miércoles','1 (08:15-08:50)',
    'ELI270 - FUNDAMENTOS DE ELECTROTECNIA   ','1','S. ZUMARAN','Cátedra',this,'C232','Inscrita');">
```

Jour, horaires, code, intitulé, paralelo, enseignant, type, salle et statut y sont explicites :
plus rien à déduire d'une position en colonne ni d'un numéro de module. `_blocks_from_consulta()`
repère le jour et le module **par leur forme** (`_match_day()`, `_MODULE_SLOT_RE`) et ne suppose
l'ordre des arguments qu'après le module. Trois précautions :

- les arguments sont découpés par `_split_js_args()`, pas par `split(",")` — les libellés du
  portail contiennent des virgules (« ORTIZ, ALEJANDRO ») ;
- le portail découpe la journée en modules d'environ 35 minutes et répète la même case sur
  chacun : les modules **consécutifs** d'un même cours sont refusionnés (`_block_from_run()`) ;
- le séparateur d'heure est inconstant — « 12:30-13.05 » se rencontre tel quel.

Cátedra et Ayudantía d'une même matière portent le même code : le type est ajouté au titre,
sans quoi deux créneaux distincts seraient indiscernables dans l'agenda.

Les cases « TOPE DE HORARIO » utilisent `ConsultaTexto()` et sont ignorées.

#### 2. L'analyse visuelle des tables — le recours

Conservée pour le cas où cette page changerait de forme. Chaque `<table>` est développée
en grille par `_table_to_grid()`, qui matérialise `rowspan`/`colspan` en dupliquant le contenu
sur les cases couvertes : sans cela les cellules d'une ligne se décalent et les cours changent
de jour. La table produisant le plus de créneaux l'emporte.

Deux orientations sont gérées (jours en colonnes, ou en lignes puis transposées). Les lignes
consécutives portant un texte identique sont refusionnées, ce qui couvre à la fois le `rowspan`
et les vues qui répètent la cellule sur chaque module.

`MODULE_TIMES` n'est qu'un **repli du repli**, employé quand l'en-tête annonce un numéro de
module sans horaire. Ces blocs sortent avec `time_source = "module"`, sont marqués « horaire
déduit » dans la prévisualisation et portent un avertissement dans leur description. **Ces
horaires n'ont jamais pu être vérifiés**, et la page réelle les contredit : elle découpe la
journée en modules d'environ 35 minutes (`1 (08:15-08:50)`, `2 (08:50-09:25)`…), là où cette
table suppose des blocs de 70 minutes. Sur le portail d'aujourd'hui, la lecture `Consulta()`
donne les horaires exacts et ce repli ne sert jamais — corriger la table si un jour il resurgit.

Ce qu'un motif ne reconnaît pas n'est jamais perdu : le texte brut de la cellule est conservé
dans `raw` et repris intégralement dans la description de l'événement.

### Synchronisation plutôt qu'import

`block_to_google_event()` produit un `iCalUID` déterministe
(`siga-<sha1(code|paralelo|jour|horaires)>@siga.usm.cl`), poussé via `events().import_()` :
rejouer la synchronisation **met à jour** les événements au lieu de les dupliquer.

L'heure part en **heure locale accompagnée de `timeZone`**, et non en instant UTC suffixé `Z` —
à l'inverse de la version statique. Une récurrence hebdomadaire doit suivre les changements
d'heure chiliens, qu'un instant absolu figerait au décalage du premier jour.

### Ce que le mot de passe ne touche pas

Il est passé à `login()` puis abandonné : jamais en attribut du client, jamais dans
`_PLANNING_STORE`, jamais dans la session Flask, jamais journalisé. `_PLANNING_STORE` suit la
même règle que `_CREDENTIALS_STORE` — mémoire du processus, cookie porteur d'un simple `sid`.

`/siga/diagnostic` sert le HTML brut récupéré, données personnelles comprises : acceptable
tant que le serveur n'écoute que sur `127.0.0.1`, à revoir si cela changeait. Deux
paramètres pour s'y retrouver — le portail empile une dizaine de documents : `?doc=<fragment>`
filtre sur l'URL, `?save=1` écrit un fichier par document dans `SIGA_DUMP_DIR` (`.siga-dump/`
par défaut, couvert par `.gitignore`, vidé à chaque appel). Ces fichiers portent les mêmes
données personnelles que la page : les supprimer une fois le débogage terminé.

## Développement

```bash
# Version statique — le port 8080 doit correspondre à l'origine déclarée dans Google Cloud
python -m http.server 8080

# Variante Flask
pip install -r requirements.txt   # nécessite credentials.json à la racine
python app.py                     # http://localhost:5000

# Tests du parseur SIGA — sans réseau ni dépendance de test
python test_siga.py
```

Pas de linter ni de CI. Le seul test est [test_siga.py](test_siga.py), qui couvre les
heuristiques d'extraction du planning sur des grilles reconstituées (`rowspan`, cellule
répétée, grille transposée, horaires absents, table de mise en page) et la génération des
événements Google. Il existe parce que la page réelle n'est pas consultable sans compte
étudiant : ces heuristiques sont écrites sans jamais avoir vu leur cible, et une régression
y passerait autrement inaperçue. Le lancer après toute retouche de `siga.py`.

## Conventions

- Toute la langue visible (interface, commentaires, messages d'erreur) est en **français**.
- Les sections de code sont séparées par des commentaires `// ── Titre ───…` ; conserver ce style.
- `js/ical.min.js` est **ical.js 1.5.0** (2022-01-06), dépendance tierce vendorisée sous
  **MPL 2.0** : ne jamais la modifier à la main. En cas de mise à jour, **reporter l'en-tête
  d'avis de licence** en tête du nouveau fichier — la MPL l'exige (Exhibit A) — et mettre à
  jour version, date et empreinte dans [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
  Attention : les versions 2.x sont en modules ES et cassent la globale `ICAL` dont dépend
  `js/parser.js`.
- Les emojis font partie du vocabulaire de l'interface (boutons, toasts, tableaux) — les garder.

## Pièges connus

- **Secrets** : `credentials.json` (variante Flask) contient un client secret. Il est couvert
  par [.gitignore](.gitignore) ; vérifier avant tout commit touchant à la configuration.
- **Cohérence des ports** : `8080` (statique) et `5000` (Flask) apparaissent en dur dans le
  README, `js/gcal.js` et la configuration Google Cloud. Un changement doit être répercuté partout.
- **URL du dépôt** : les liens GitHub de `index.html` et `templates/index.html` pointent vers
  `BretzelCoder/GoogleAgendaAssistant`. À corriger en cas de fork ou de renommage.
- **Fragilité assumée du parseur SIGA** : `siga.py` cible une page dont la structure exacte
  n'a jamais pu être observée (elle exige un compte étudiant). L'extraction est donc
  volontairement heuristique et ne lève pas d'exception sur une mise en page inattendue : elle
  renvoie zéro créneau, et `/siga/diagnostic` sert la page brute pour ajuster. Toute
  modification du portail se traduira par une prévisualisation vide, jamais par un import
  silencieusement faux.
