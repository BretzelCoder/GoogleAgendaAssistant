# Notices de licences tierces

Ce projet est distribué sous licence MIT (voir [LICENSE](LICENSE)), à l'exception des
composants tiers listés ci-dessous, qui restent soumis à leur propre licence.

---

## ical.js

- **Fichier** : `js/ical.min.js`
- **Version** : **1.5.0**, publiée le **6 janvier 2022**
- **Release** : https://github.com/kewisch/ical.js/releases/tag/v1.5.0 (tag `v1.5.0`)
- **Origine** : https://github.com/kewisch/ical.js
- **Auteurs** : Philipp Kewisch et les contributeurs d'ical.js
- **Licence** : Mozilla Public License 2.0 (MPL-2.0) — https://mozilla.org/MPL/2.0/

Bibliothèque de parsing et de manipulation iCalendar (RFC 5545) utilisée par la version
statique de l'application pour analyser les fichiers `.ics` dans le navigateur.

### Identification de la version

Le fichier minifié ne contient aucun numéro de version. La version 1.5.0 a été établie par
comparaison d'empreinte avec les artefacts publiés — la correspondance est exacte, octet
pour octet, avec `build/ical.min.js` de la release v1.5.0 :

| | |
|---|---|
| Artefact amont | `build/ical.min.js` (release `v1.5.0`) |
| Taille | 81 064 octets |
| SHA-256 | `ba8b552a5b54bf99de2ac225671af151c71b6b43daa6dbac163ea9fb0f12a27b` |

Vérification (l'empreinte porte sur le fichier **sans** l'en-tête de licence ajouté, soit à
partir de la ligne 10) :

```bash
tail -n +10 js/ical.min.js | sha256sum
curl -s https://cdn.jsdelivr.net/npm/ical.js@1.5.0/build/ical.min.js | sha256sum
```

Les deux commandes doivent produire l'empreinte ci-dessus.

### Forme du code source

Le fichier présent dans ce dépôt est une **version minifiée**, qui ne constitue pas la
« Source Code Form » au sens de la MPL 2.0. Le code source correspondant à cette version
précise est disponible publiquement au tag `v1.5.0` du dépôt amont, conformément à la
section 3.2 de la licence.

### Mise à jour

La 1.5.0 est la dernière version de la branche 1.x. Les versions 2.x (2.2.1 au 8 août 2025)
sont distribuées en modules ES et réorganisent les artefacts (`dist/` au lieu de `build/`) :
une montée de version constituerait un changement cassant pour `js/parser.js`, qui dépend de
la globale `ICAL` exposée par le build 1.x.

### Modifications

Le fichier n'a fait l'objet d'**aucune modification fonctionnelle**. Seul un en-tête de
commentaire portant l'avis de licence (Exhibit A de la MPL 2.0) a été ajouté en tête de
fichier.

---

## Pourquoi le projet reste sous MIT

La MPL 2.0 est un copyleft **au niveau du fichier**, et non du projet. Sa section 3.3
(« Distribution of a Larger Work ») autorise explicitement à distribuer un ensemble plus
large sous les termes de son choix, dès lors que les fichiers couverts par la MPL restent
soumis à celle-ci et que leurs avis de licence sont préservés.

Concrètement :

- `js/ical.min.js` reste sous MPL 2.0, avec son avis de licence en en-tête ;
- tout le reste du dépôt — écrit pour ce projet — reste sous licence MIT ;
- il n'y a **aucune obligation** de relicencier le projet en MPL 2.0.

Ces deux licences sont compatibles pour cet usage.

---

## Services externes (non redistribués)

Ces ressources sont chargées à l'exécution et ne sont pas incluses dans le dépôt :

| Ressource | Chargée depuis | Utilisée par |
|---|---|---|
| Google Identity Services | `https://accounts.google.com/gsi/client` | Version statique (`index.html`) |
| Google Calendar API v3 | `https://www.googleapis.com/calendar/v3` | Les deux versions |

Les dépendances Python de la variante Flask sont déclarées dans
[requirements.txt](requirements.txt) et ne sont pas redistribuées ici ; chacune conserve
la licence de son éditeur.
