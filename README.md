# Latin Trainer

Application web pédagogique pour l'apprentissage du latin : analyse grammaticale guidée par IA, corpus de vocabulaire, quiz variés.

## Prérequis

- Debian/Ubuntu avec Python 3.9+
- Une clé API OpenAI (`gpt-4o-mini`)

## Installation sur Debian

```bash
# 1. Prérequis système
sudo apt update
sudo apt install python3 python3-pip python3-venv -y

# 2. Créer et activer l'environnement virtuel
cd latin-trainer
python3 -m venv venv
source venv/bin/activate

# 3. Installer les dépendances
pip install flask openai python-dotenv

# 4. Configurer la clé API
cp .env.example .env
nano .env   # remplacer sk-...votre-clé-ici... par votre vraie clé

# 5. Lancer l'application
python app.py
# → Accessible sur http://IP-DE-VOTRE-VM:5000
```

## Lancement automatique au démarrage (optionnel)

```bash
# Créer un service systemd
sudo nano /etc/systemd/system/latin-trainer.service
```

Contenu du fichier :

```ini
[Unit]
Description=Latin Trainer
After=network.target

[Service]
Type=simple
User=VOTRE_USER
WorkingDirectory=/chemin/vers/latin-trainer
ExecStart=/chemin/vers/latin-trainer/venv/bin/python app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable latin-trainer
sudo systemctl start latin-trainer
```

## Structure du projet

```
latin-trainer/
├── app.py              # Application Flask + routes + logique IA
├── database.py         # Initialisation SQLite + fonctions CRUD
├── latin_trainer.db    # Base de données (créée au premier lancement)
├── .env                # Clé API (à créer depuis .env.example)
├── .env.example        # Modèle de configuration
├── requirements.txt
└── templates/
    ├── index.html      # Accueil + upload de textes
    ├── trainer.html    # Analyseur phrase par phrase
    ├── corpus.html     # Gestion du corpus + export CSV
    └── quiz.html       # Quiz (4 types de questions)
```

## Fonctionnalités

### Module 1 — Analyseur de texte

1. Uploadez un texte latin (`.txt` ou collé directement)
2. L'IA extrait automatiquement le vocabulaire
3. Parcourez chaque phrase en 6 étapes guidées :
   - Propositions → Verbes → Prépositions → Noms → Traduction → Mot à mot
4. À chaque étape : 3 tentatives avec indices progressifs, puis réponse complète

### Module 2 — Corpus

- Tableau de tout le vocabulaire extrait avec filtres
- Export CSV du corpus (complet ou filtré)
- Suppression de textes avec cascade
- Accès à l'historique des quiz

### Module 3 — Quiz

4 types de questions disponibles :
- **Latin → Français** : traduction libre
- **Français → Latin** : version inverse
- **Forme → Analyse** : menus déroulants (catégorie, cas, temps, mode, personne, nombre)
- **Phrase lacunaire** : compléter une phrase avec le mot manquant

Options : source (texte spécifique ou tout le corpus), nombre de questions, filtre par catégorie.

## Notes techniques

- Base de données SQLite locale (`latin_trainer.db`), aucune dépendance externe
- Tous les appels OpenAI se font côté serveur (Flask), jamais côté client
- L'état du quiz et de l'analyseur est géré en JavaScript côté client
- Compatible Python 3.9+
