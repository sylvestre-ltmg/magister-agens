# Magister Agens

> *Magister Agens* — "the agentic tutor" (*agens*, the Latin root of "agent"). A web app to learn Latin, powered by Claude.

AI-guided grammatical analysis, vocabulary corpus, and varied quizzes — wrapped in an Ancient-Rome theme and usable on mobile.

*[Français ci-dessous](#français)*

---

## English

### Features

**Text analyzer** — paste or upload a Latin text; Claude extracts the vocabulary automatically. Work through each sentence in 6 guided steps (clauses → verbs → prepositions → nouns → translation → word-by-word), with progressive hints over several attempts.

**Corpus** — browse all extracted vocabulary with filters, export to CSV, delete texts (cascade), and review quiz history.

**Quiz** — four question types:
- **Latin → French** (free translation)
- **French → Latin** (reverse)
- **Form → Analysis** (dropdowns: category, case, tense, mood, person, number)
- **Cloze** (fill in the missing word)

Token-efficient by design: exact answers are checked locally (no API call), AI evaluation is batched at the end of a quiz, and each task uses a trimmed system prompt.

### Requirements

- Python 3.9+
- An [Anthropic API key](https://console.anthropic.com/) (Claude)

### Install

```bash
git clone https://github.com/sylvestre-ltmg/magister-agens.git
cd magister-agens

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set ANTHROPIC_KEY

python app.py            # serves on http://localhost:5002
```

### Configuration (`.env`)

| Variable | Description | Default |
|---|---|---|
| `ANTHROPIC_KEY` | Anthropic API key (required) | — |
| `PORT` | Listening port | `5002` |
| `CLAUDE_MODEL` | Model id | `claude-haiku-4-5-20251001` |

### Run as a service (optional)

```ini
# /etc/systemd/system/magister-agens.service
[Unit]
Description=Magister Agens
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/path/to/magister-agens
ExecStart=/path/to/magister-agens/venv/bin/python app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now magister-agens
```

### Project structure

```
magister-agens/
├── app.py            # Flask app, routes, Claude calls
├── database.py       # SQLite init + CRUD
├── requirements.txt
├── .env.example
├── static/           # theme.css (Roma Antiqua), usage.js
└── templates/        # index, trainer, corpus, quiz
```

The SQLite database (`latin_trainer.db`) is created on first run. All Claude calls happen server-side; the key never reaches the browser.

### Tech

Flask · SQLite · Claude (Haiku 4.5) via REST. No JS framework.

---

## Français

> *Magister Agens* — « le précepteur agentique » (*agens*, la racine latine d'« agent »). Une application web pour apprendre le latin, propulsée par Claude.

Analyse grammaticale guidée par IA, corpus de vocabulaire et quiz variés — dans un thème Rome antique, utilisable sur mobile.

### Fonctionnalités

**Analyseur de texte** — collez ou importez un texte latin ; Claude en extrait le vocabulaire automatiquement. Parcourez chaque phrase en 6 étapes guidées (propositions → verbes → prépositions → noms → traduction → mot à mot), avec des indices progressifs au fil des tentatives.

**Corpus** — tout le vocabulaire extrait, avec filtres, export CSV, suppression de textes (cascade) et historique des quiz.

**Quiz** — quatre types de questions :
- **Latin → Français** (traduction libre)
- **Français → Latin** (version inverse)
- **Forme → Analyse** (menus : catégorie, cas, temps, mode, personne, nombre)
- **Phrase lacunaire** (compléter le mot manquant)

Sobre en tokens : les réponses exactes sont validées en local (sans appel API), l'évaluation IA est regroupée en fin de quiz, et chaque tâche utilise un *system prompt* allégé.

### Prérequis

- Python 3.9+
- Une [clé API Anthropic](https://console.anthropic.com/) (Claude)

### Installation

```bash
git clone https://github.com/sylvestre-ltmg/magister-agens.git
cd magister-agens

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# éditez .env et renseignez ANTHROPIC_KEY

python app.py            # disponible sur http://localhost:5002
```

### Configuration (`.env`)

| Variable | Description | Défaut |
|---|---|---|
| `ANTHROPIC_KEY` | Clé API Anthropic (requise) | — |
| `PORT` | Port d'écoute | `5002` |
| `CLAUDE_MODEL` | Identifiant du modèle | `claude-haiku-4-5-20251001` |

### Lancement en service (optionnel)

Voir le fichier systemd de la section anglaise (adapter `User` et les chemins).

### Structure

```
magister-agens/
├── app.py            # App Flask, routes, appels Claude
├── database.py       # Init SQLite + CRUD
├── requirements.txt
├── .env.example
├── static/           # theme.css (Roma Antiqua), usage.js
└── templates/        # index, trainer, corpus, quiz
```

La base SQLite (`latin_trainer.db`) est créée au premier lancement. Tous les appels Claude sont faits côté serveur ; la clé n'atteint jamais le navigateur.

### Technique

Flask · SQLite · Claude (Haiku 4.5) en REST. Aucun framework JS.
