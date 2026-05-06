# 📅 ICS → Google Calendar

Application web 100 % statique pour importer des fichiers `.ics` (ou flux iCalendar) directement dans **Google Agenda** — sans backend, sans serveur, hébergeable gratuitement sur **GitHub Pages**.

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

### Étape 5 — Configurer l'application

Ouvrez l'application dans votre navigateur, collez votre **Client ID** dans le champ en haut et cliquez **Enregistrer**. La page se recharge automatiquement.

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
| *CORS ou réseau* | L'URL du flux refuse les requêtes navigateur | Téléchargez le `.ics` manuellement et utilisez l'upload |

---

## 🌐 Déploiement sur GitHub Pages

1. Forkez ou clonez ce dépôt sur votre compte GitHub
2. Dans les paramètres du dépôt : **Settings → Pages → Source : Deploy from a branch → main / (root)**
3. Votre app sera disponible sur `https://votre-compte.github.io/nom-du-repo`
4. Ajoutez cette URL dans les **Origines JavaScript autorisées** de votre Client ID Google (étape 4 ci-dessus)

---

## 🔒 Vie privée & sécurité

- **Aucun serveur** : toute la logique s'exécute dans votre navigateur
- **Aucune donnée transmise** : ni le fichier ICS, ni le token Google ne quittent votre navigateur
- **Token temporaire** : le token OAuth expire après 1 heure (standard Google)
- **Client ID public** : c'est normal — seuls les domaines que vous autorisez explicitement peuvent l'utiliser

---

## 🗂 Structure du projet

```
ics-to-gcal/
├── index.html        # Page principale (app complète)
├── css/
│   └── style.css     # Styles
├── js/
│   ├── ical.min.js   # Bibliothèque de parsing iCalendar
│   ├── parser.js     # Conversion ICS → objets JS
│   ├── gcal.js       # Client Google Calendar API + OAuth
│   └── app.js        # Logique & interface utilisateur
└── README.md
```

---

## 📄 Licence

MIT — libre d'utilisation, de modification et de redistribution.
