# 📅 ICS → Google Calendar

Application web 100% statique pour importer des fichiers `.ics` (ou flux iCalendar) directement dans **Google Agenda** — sans backend, sans serveur, hébergeable gratuitement sur **GitHub Pages**.

🔗 **Démo live** : `https://votre-compte.github.io/ics-to-gcal`

---

## ✨ Fonctionnalités

- 📂 **Upload** d'un fichier `.ics` (glisser-déposer)
- 🔗 **URL** d'un flux iCalendar distant
- 👀 **Prévisualisation** des événements avant import (avec sélection)
- 🔁 **Événements récurrents** (RRULE) supportés nativement
- 🔎 **Détection des doublons** — 3 stratégies au choix :
  - Ignorer · Mettre à jour · Dupliquer
- 🗂 **Choix de l'agenda** de destination
- 🔐 **OAuth2 côté client** — aucun mot de passe stocké, aucun serveur
- 🌐 **100% statique** — hébergeable sur GitHub Pages gratuitement

---

## 🚀 Mise en place

### 1. Forker / cloner le dépôt

```bash
git clone https://github.com/votre-compte/ics-to-gcal.git
cd ics-to-gcal
```

### 2. Obtenir un Client ID Google

> Durée : ~5 minutes · Gratuit · Unique

1. Allez sur [console.cloud.google.com](https://console.cloud.google.com)
2. Créez un nouveau projet (ex : `ics-to-gcal`)
3. Activez l'**API Google Calendar** :
   - *APIs & Services → Enable APIs → Google Calendar API → Activer*
4. Créez un identifiant OAuth :
   - *Credentials → Create Credentials → OAuth client ID*
   - Type d'application : **Application Web**
   - Nom : `ics-to-gcal`
5. Ajoutez les **URI de redirection autorisés** :
   ```
   http://localhost:8080          ← pour tester en local
   https://votre-compte.github.io ← pour GitHub Pages
   ```
6. Copiez le **Client ID** généré (format : `XXXXXXXX.apps.googleusercontent.com`)

### 3. Configurer l'application

Ouvrez l'application dans votre navigateur, collez votre **Client ID** dans le champ prévu et cliquez **Enregistrer**. Il est stocké dans votre `localStorage` (jamais envoyé nulle part).

### 4. Activer GitHub Pages

Dans votre dépôt GitHub :
- *Settings → Pages → Source : Deploy from a branch → main / (root)*
- Votre app sera disponible sur `https://votre-compte.github.io/ics-to-gcal`

> N'oubliez pas d'ajouter cette URL dans les URIs autorisés de votre projet Google Cloud (étape 2.5).

---

## 🗂 Structure du projet

```
ics-to-gcal/
├── index.html        # Page principale (app complète)
├── css/
│   └── style.css     # Styles
├── js/
│   ├── parser.js     # Parsing ICS (via ical.js)
│   ├── gcal.js       # Client Google Calendar API
│   └── app.js        # Logique & UI
└── README.md
```

---

## 🔒 Vie privée & sécurité

- **Aucun serveur** : toute la logique s'exécute dans votre navigateur
- **Aucune donnée transmise** : ni le fichier ICS, ni le token Google ne quittent votre navigateur
- **Token temporaire** : le token OAuth expire après 1 heure (standard Google)
- **Client ID public** : c'est normal — il identifie l'application, pas vous. Seuls les domaines que vous autorisez peuvent l'utiliser.

---

## ⚠️ Limitation CORS pour les URL distantes

Lorsque vous saisissez une URL de flux ICS, votre navigateur effectue une requête directe vers ce serveur. Si ce serveur ne renvoie pas les en-têtes CORS appropriés, la requête sera bloquée.

**Solution** : téléchargez le fichier `.ics` manuellement et utilisez l'upload.

---

## 📄 Licence

MIT — libre d'utilisation, de modification et de redistribution.
