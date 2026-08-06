# 📅 ICS → Google Calendar

Application web 100 % statique pour importer des fichiers `.ics` (ou flux iCalendar) directement dans **Google Agenda** — sans backend, sans serveur, hébergeable gratuitement sur **GitHub Pages**.

> **Deux implémentations coexistent dans ce dépôt.** La version statique (`index.html` + `js/`) est celle décrite ci-dessous et celle déployée sur GitHub Pages. Une seconde version, **Flask**, est également présente (`app.py` + `templates/`) : elle offre moins de fonctionnalités et s'exécute en local uniquement. Voir [Variante Flask](#-variante-flask-serveur-local).

---

## ✨ Fonctionnalités

- 📂 Upload d'un fichier `.ics` (glisser-déposer)
- 🔗 Import depuis une URL de flux iCalendar
- 👀 Prévisualisation des événements avant import (avec sélection individuelle)
- 🗂 Choix de l'agenda de destination
- 🔎 Gestion des doublons : ignorer · mettre à jour · dupliquer
- 🔐 OAuth2 côté client — aucun mot de passe stocké, aucun serveur

---

## 🚀 Mise en place

La configuration se fait **une seule fois** et prend environ 10 minutes.

### Prérequis

| | Version statique | Variante Flask |
|---|---|---|
| Compte Google | ✅ requis | ✅ requis |
| Navigateur récent | ✅ requis | ✅ requis |
| Python | 3.x — uniquement pour servir les fichiers ; n'importe quel serveur HTTP fait l'affaire | **3.8 ou plus** (imposé par Flask 3.0) |
| Dépendances à installer | ❌ aucune — les bibliothèques sont déjà dans `js/` | `pip install -r requirements.txt` |

### Étape 0 — Récupérer le projet

```bash
git clone https://github.com/BretzelCoder/GoogleAgendaAssistant.git
cd GoogleAgendaAssistant
```

> Sans Git : **Code → Download ZIP** sur la page GitHub du dépôt, puis décompressez-le.
> Toutes les commandes qui suivent s'exécutent depuis la racine du dossier obtenu.

Si votre objectif est d'héberger l'application plutôt que de l'utiliser en local,
allez directement à [Déploiement sur GitHub Pages](#-déploiement-sur-github-pages).

### Étape 1 — Créer un projet Google Cloud

1. Rendez-vous sur [console.cloud.google.com](https://console.cloud.google.com)
2. Cliquez sur le sélecteur de projet en haut → **Nouveau projet**
3. Donnez-lui un nom (ex. `ics-to-gcal`) et confirmez

### Étape 2 — Activer l'API Google Calendar

1. Dans le menu : **APIs & Services → Enable APIs and Services**
2. Recherchez **Google Calendar API**
3. Cliquez sur le résultat puis sur **Enable**

> ⚠️ Sans cette étape, vous obtiendrez l'erreur *"Google Calendar API has not been used in project"* lors de l'import.

### Étape 3 — Configurer l'écran de consentement OAuth

1. **APIs & Services → OAuth consent screen**
2. Choisissez **External** → **Create**
3. Remplissez les champs obligatoires (nom de l'app, email de support)
4. Cliquez **Save and Continue** jusqu'à la section **Test users**
5. Dans **Test users** → **+ Add users** → ajoutez votre adresse Gmail
6. Terminez la configuration

> ⚠️ Tant que l'app est en mode *Testing*, seuls les emails de la liste peuvent se connecter. Pour un usage personnel, c'est suffisant.

### Étape 4 — Créer un identifiant OAuth

1. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
2. Type d'application : **Application Web**
3. Dans **Origines JavaScript autorisées**, ajoutez :
   ```
   http://localhost:8080
   https://votre-compte.github.io
   ```
4. Cliquez **Create**
5. Copiez le **Client ID** généré (format `XXXXXXXX.apps.googleusercontent.com`)

> Le Client ID est une valeur publique — il identifie votre application, pas vous.

### Étape 5 — Lancer l'application en local

Google refuse l'OAuth depuis un fichier ouvert en `file://`. Il faut servir le dossier en HTTP,
**sur le port 8080** (c'est l'origine déclarée à l'étape 4) :

```bash
# Depuis la racine du dépôt
python -m http.server 8080
```

Puis ouvrez [http://localhost:8080](http://localhost:8080).

> Toute autre méthode fonctionne (`npx serve -l 8080`, extension *Live Server*, …) tant que
> l'URL finale correspond exactement à une origine JavaScript autorisée de votre Client ID.

### Étape 6 — Configurer le Client ID dans l'application

Collez votre **Client ID** dans le champ en haut de la page et cliquez **Enregistrer**.
La page se recharge automatiquement.

> Le Client ID est stocké dans le `localStorage` du navigateur (clé `ics_gcal_client_id`).
> Il reste donc en place d'une session à l'autre, et par navigateur.

---

## 📖 Utilisation

### 1. Se connecter

Cliquez sur **Se connecter avec Google** et sélectionnez votre compte Gmail.

> Si Chrome bloque la popup : cliquez sur l'icône de popup bloquée dans la barre d'adresse et autorisez `localhost:8080` (ou votre domaine GitHub Pages).

### 2. Choisir la source ICS

Deux options :

- **Fichier .ics** — glissez-déposez le fichier ou cliquez pour parcourir
- **URL** — collez l'adresse d'un flux iCalendar distant

Cliquez ensuite sur **🔍 Analyser**.

> ⚠️ Certaines URLs de flux iCalendar refusent les requêtes depuis un navigateur (CORS). Si l'analyse échoue avec une URL, téléchargez le fichier `.ics` manuellement et utilisez l'upload.

### 3. Prévisualiser et sélectionner

Un tableau liste tous les événements détectés avec leur titre, dates et indicateurs (récurrent, lieu, invalide). Vous pouvez :

- Décocher des événements pour les exclure de l'import
- Utiliser la case en en-tête pour tout sélectionner / désélectionner

### 4. Choisir les options d'import

- **Agenda de destination** — sélectionnez l'agenda Google dans lequel importer
- **Gestion des doublons** :
  - *Ignorer* — les événements déjà présents (même UID) sont ignorés
  - *Mettre à jour* — les événements existants sont écrasés
  - *Importer quand même* — crée un doublon sans vérification

### 5. Lancer l'import

Cliquez sur **⬆️ Importer**. Une barre de progression s'affiche. À la fin, un résumé indique le nombre d'événements importés, mis à jour, ignorés et les éventuelles erreurs.

---

## ❓ Erreurs fréquentes

| Erreur | Cause | Solution |
|--------|-------|----------|
| *access_denied* | Votre email n'est pas dans les utilisateurs test | APIs & Services → OAuth consent screen → Test users → ajoutez votre email |
| *Google Calendar API has not been used* | L'API n'est pas activée | APIs & Services → Enable APIs → activez **Google Calendar API** |
| *La popup a été bloquée* | Chrome bloque la popup OAuth | Autorisez les popups pour ce domaine dans la barre d'adresse |
| *Origine non autorisée* | L'URL d'où vous accédez n'est pas déclarée | Ajoutez l'URL dans **Origines JavaScript autorisées** de votre Client ID |
| *Fichier ICS invalide* | Le fichier est corrompu ou mal encodé | Vérifiez que le fichier s'ouvre correctement dans un éditeur de texte |
| *CORS ou réseau* | L'URL du flux refuse les requêtes navigateur | Téléchargez le `.ics` manuellement et utilisez l'upload, ou passez par la [variante Flask](#-variante-flask-serveur-local) |
| *Client ID invalide* | Le format saisi ne se termine pas par `.apps.googleusercontent.com` | Recopiez le Client ID complet depuis Google Cloud Console |
| *Impossible de charger Google* | Le script Google Identity Services n'a pas pu être chargé (bloqueur de pub, hors-ligne) | Désactivez le bloqueur sur ce domaine et rechargez |
| Le bouton **Se connecter** reste grisé | Aucun Client ID enregistré | Renseignez le Client ID dans le champ en haut de page (étape 6) |
| La page ne fait rien en `file://` | L'OAuth Google exige une origine HTTP | Servez le dossier via `python -m http.server 8080` (étape 5) |

---

## 🌐 Déploiement sur GitHub Pages

1. Forkez ou clonez ce dépôt sur votre compte GitHub
2. Dans les paramètres du dépôt : **Settings → Pages → Source : Deploy from a branch → main / (root)**
3. Votre app sera disponible sur `https://votre-compte.github.io/nom-du-repo`
4. Ajoutez cette URL dans les **Origines JavaScript autorisées** de votre Client ID Google (étape 4 ci-dessus)

---

## 🐍 Variante Flask (serveur local)

Le dépôt contient aussi une implémentation **Flask** (`app.py`), antérieure et plus simple.
Elle fait l'OAuth **côté serveur**, ce qui implique un *client secret* et donc un vrai serveur :
elle **ne peut pas** être déployée sur GitHub Pages.

### Quand l'utiliser

Elle reste utile si vous préférez ne pas exposer de Client ID dans le navigateur, ou si
les restrictions CORS de votre flux ICS bloquent la version statique (le téléchargement de
l'URL est fait par le serveur Python, pas par le navigateur).

### Fonctionnalités par rapport à la version statique

| Fonctionnalité | Statique | Flask |
|---|:---:|:---:|
| Upload `.ics` / URL de flux | ✅ | ✅ |
| Téléchargement d'URL sans blocage CORS | ❌ | ✅ |
| Prévisualisation + sélection des événements | ✅ | ❌ |
| Choix de l'agenda de destination | ✅ | ✅ |
| Stratégie de doublons configurable | ✅ | ❌ (toujours *import par UID*) |
| Événements récurrents (`RRULE`) | ✅ | ❌ (récurrence non transmise) |
| Barre de progression | ✅ | ❌ |
| Hébergeable sur GitHub Pages | ✅ | ❌ |

### Installation

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### Identifiants Google

Cette variante nécessite un identifiant OAuth **avec secret**, différent de celui de l'étape 4 :

1. **APIs & Services → Credentials → Create Credentials → OAuth client ID → Application Web**
2. Dans **URI de redirection autorisés**, ajoutez :
   ```
   http://localhost:5000/oauth2callback
   ```
3. **Download JSON** et enregistrez le fichier sous `credentials.json` à la racine du dépôt

> 🔐 `credentials.json` contient un **client secret** : ne le commitez jamais.
> Il est listé dans `.gitignore`.

### Lancement

```bash
# Facultatif : fixer la clé de session pour rester connecté d'un redémarrage à l'autre
# Windows PowerShell
$env:SECRET_KEY = "une-valeur-aleatoire"
# macOS / Linux
export SECRET_KEY="une-valeur-aleatoire"

python app.py
```

L'application écoute sur [http://localhost:5000](http://localhost:5000).

**Variables d'environnement reconnues :**

| Variable | Défaut | Rôle |
|---|---|---|
| `SECRET_KEY` | *aléatoire à chaque démarrage* | Clé de signature des sessions Flask |
| `GOOGLE_CLIENT_SECRETS` | `credentials.json` | Chemin du fichier d'identifiants OAuth |
| `FLASK_DEBUG` | *désactivé* | `1` active le débogueur Werkzeug (**console d'exécution de code** — développement uniquement) |

> ⚠️ `app.py` force `OAUTHLIB_INSECURE_TRANSPORT=1` (OAuth autorisé en HTTP). C'est
> acceptable parce que le serveur n'écoute que sur `127.0.0.1`, **pas** pour une exposition
> sur le réseau.

---

## 🔒 Vie privée & sécurité

### Version statique

- **Aucun serveur** : toute la logique s'exécute dans votre navigateur
- **Aucune donnée transmise** : ni le fichier ICS, ni le token Google ne quittent votre navigateur — les seules requêtes sortantes vont vers les API Google
- **Token en mémoire** : le token d'accès n'est jamais persisté ; il disparaît au rechargement de la page. Seul le Client ID est conservé (`localStorage`)
- **Token temporaire** : le token OAuth expire après 1 heure (standard Google)
- **Client ID public** : c'est normal — seuls les domaines que vous autorisez explicitement peuvent l'utiliser

### Variante Flask

- **Aucun jeton dans le cookie** : les sessions Flask sont signées mais non chiffrées, donc lisibles par le navigateur. Le cookie ne contient qu'un identifiant opaque ; token et refresh token restent en mémoire du serveur et disparaissent à l'arrêt
- **Écoute locale seulement** (`127.0.0.1`), débogueur désactivé par défaut
- **URLs distantes filtrées** : le téléchargement d'un ICS par URL refuse les adresses privées, locales et réservées, y compris après redirection (protection SSRF)
- `credentials.json` contient un **client secret** : gardez-le hors du dépôt
- Prévue pour un usage **local uniquement** (OAuth en HTTP autorisé)

---

## 🗂 Structure du projet

```
GoogleAgendaAssistant/
│
│  ── Version statique (principale, déployée sur GitHub Pages) ──
├── index.html          # Page principale (app complète, 3 étapes)
├── css/
│   └── style.css       # Styles
├── js/
│   ├── ical.min.js     # Bibliothèque tierce de parsing iCalendar (ical.js 1.5.0, MPL 2.0)
│   ├── parser.js       # ICSParser — VEVENT → objets Google Calendar
│   ├── gcal.js         # GCal — client REST Calendar API + OAuth (GIS)
│   └── app.js          # Logique & interface utilisateur
│
│  ── Variante Flask (locale, optionnelle) ──
├── app.py              # Serveur Flask (OAuth côté serveur + import)
├── templates/
│   └── index.html      # Gabarit Jinja2 (CSS et JS inline)
├── requirements.txt    # Dépendances Python de la variante Flask
│
├── README.md                # Ce fichier — installation et usage
├── CLAUDE.md                # Documentation interne (architecture, conventions)
├── LICENSE                  # MIT
└── THIRD-PARTY-NOTICES.md   # Licences des composants tiers (ical.js — MPL 2.0)
```

> `requirements.txt` ne concerne **que** la variante Flask. La version statique n'a aucune
> dépendance à installer : les bibliothèques sont déjà dans `js/`.

---

## 📄 Licence

MIT — libre d'utilisation, de modification et de redistribution. Voir [LICENSE](LICENSE).

**Exception :** `js/ical.min.js` est une bibliothèque tierce
([ical.js](https://github.com/kewisch/ical.js)) sous **MPL 2.0**. Cette licence étant un
copyleft au niveau du fichier, elle n'affecte pas le reste du projet, qui demeure sous MIT.

Détail des composants tiers et de leurs licences : [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
