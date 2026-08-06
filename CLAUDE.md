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

## Version statique

Aucune étape de build, aucun gestionnaire de paquets. Les scripts sont chargés en balises
`<script>` dans l'ordre et communiquent par des globales.

Le fichier vide [.nojekyll](.nojekyll) à la racine désactive le passage du dépôt par Jekyll
lors de la publication GitHub Pages. Le site est du HTML/JS statique : Jekyll ne lui apporte
rien, et s'en passer évite qu'il s'invite un jour dans la boucle — notamment sur les fichiers
préfixés d'un `_`, qu'il ignore silencieusement, ou sur `templates/index.html` si ce template
Jinja2 venait à recevoir un front matter YAML, seul cas où Jekyll tenterait d'en lire les
`{% … %}` comme du Liquid.

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

La récurrence est transmise telle quelle : `event.recurrence = ['RRULE:…', 'EXDATE:…']`.

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

## Développement

```bash
# Version statique — le port 8080 doit correspondre à l'origine déclarée dans Google Cloud
python -m http.server 8080

# Variante Flask
pip install -r requirements.txt   # nécessite credentials.json à la racine
python app.py                     # http://localhost:5000
```

Il n'y a ni tests, ni linter, ni CI configurés.

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
