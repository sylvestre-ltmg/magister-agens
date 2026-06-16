import os
import re
import json
import csv
import io
import random
import unicodedata

import requests

from flask import Flask, render_template, request, jsonify, redirect, url_for, Response
from dotenv import load_dotenv

import database as db

load_dotenv()

app = Flask(__name__)

ANTHROPIC_KEY = os.getenv('ANTHROPIC_KEY')
if not ANTHROPIC_KEY:
    print("ERREUR : ANTHROPIC_KEY manquante dans le fichier .env")
    raise SystemExit(1)

MODEL = os.getenv('CLAUDE_MODEL', 'claude-haiku-4-5-20251001')

# ── Suivi de consommation Claude ───────────────────────────────────────────────
import threading

USAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'usage.json')
# Tarifs Haiku 4.5 (USD par million de tokens) : entrée $1, sortie $5
PRIX_IN_PAR_MTOK = float(os.getenv('CLAUDE_PRIX_IN', '1.0'))
PRIX_OUT_PAR_MTOK = float(os.getenv('CLAUDE_PRIX_OUT', '5.0'))
_usage_lock = threading.Lock()


def _charger_usage():
    try:
        with open(USAGE_FILE) as f:
            u = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        u = {}
    return {
        'input_tokens':  int(u.get('input_tokens', 0)),
        'output_tokens': int(u.get('output_tokens', 0)),
        'calls':         int(u.get('calls', 0)),
        'cost_usd':      float(u.get('cost_usd', 0.0)),
    }


def _enregistrer_usage(usage):
    """Cumule les tokens d'un appel Claude (champ `usage` de la réponse API)."""
    if not usage:
        return
    inp = int(usage.get('input_tokens', 0))
    out = int(usage.get('output_tokens', 0))
    with _usage_lock:
        u = _charger_usage()
        u['input_tokens'] += inp
        u['output_tokens'] += out
        u['calls'] += 1
        u['cost_usd'] = round(
            u['input_tokens'] / 1_000_000 * PRIX_IN_PAR_MTOK
            + u['output_tokens'] / 1_000_000 * PRIX_OUT_PAR_MTOK, 4)
        try:
            with open(USAGE_FILE, 'w') as f:
                json.dump(u, f)
        except OSError:
            pass


def appeler_claude(prompt, temperature=0.3, max_tokens=1500, system=None):
    """Appel à l'API Anthropic (Claude). Retourne le texte de la réponse.

    `system` permet d'alléger les appels (ex. correction de quiz) en évitant le
    long persona par défaut → moins de tokens d'entrée facturés."""
    headers = {
        "x-api-key":         ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }
    body = {
        "model":       MODEL,
        "max_tokens":  max_tokens,
        "temperature": temperature,
        "system":      SYSTEM_PROMPT if system is None else system,
        "messages":    [{"role": "user", "content": prompt}],
    }
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers=headers, json=body, timeout=60)
    r.raise_for_status()
    data = r.json()
    _enregistrer_usage(data.get("usage"))
    return data["content"][0]["text"]

SYSTEM_PROMPT = (
    "Tu es un professeur de latin expert, pédagogue et bienveillant. "
    "Tu t'adresses à un élève francophone apprenant le latin classique. "
    "Tu réponds toujours en français. "
    "Tu utilises la terminologie grammaticale latine standard : "
    "nominatif, accusatif, génitif, datif, ablatif, vocatif, "
    "proposition infinitive, cum narratif, ablatif absolu, etc. "
    "Sois encourageant mais précis. Ne donne jamais la réponse complète "
    "avant d'avoir donné au moins un indice. "
    "Quand on te demande du JSON, retourne uniquement du JSON valide, "
    "sans balises markdown et sans texte autour."
)

# System allégé pour la correction de quiz (économie de tokens : pas le persona complet)
SYSTEM_CORRECTION = (
    "Tu corriges un quiz de latin pour un élève francophone. Sois tolérant "
    "(fautes légères, synonymes, variantes mineures) et bref. "
    "Réponds uniquement en JSON valide, sans markdown ni texte autour."
)

# System minimal pour l'extraction de vocabulaire à l'import (analyse globale) :
# tâche purement JSON, aucun persona nécessaire → gros gain de tokens d'entrée
SYSTEM_EXTRACTION = (
    "Tu es un analyseur de latin. Réponds uniquement en JSON valide, "
    "sans balises markdown ni texte autour."
)

# System allégé pour l'analyse pas-à-pas (trainer) : pédagogie conservée, persona réduit
SYSTEM_TRAINER = (
    "Tu es un professeur de latin concis pour un élève francophone. Tu réponds "
    "en français avec la terminologie grammaticale standard (nominatif, accusatif, "
    "génitif, datif, ablatif, vocatif, ablatif absolu, proposition infinitive, etc.). "
    "Tu donnes des indices progressifs selon le nombre de tentatives. "
    "Réponds uniquement en JSON valide, sans markdown ni texte autour."
)

ETAPES = [
    "Identifier et délimiter les propositions (principale, subordonnées...)",
    "Trouver chaque verbe, donner sa forme et sa traduction",
    "Trouver les prépositions et les traduire",
    "Identifier les noms, leur cas, leur fonction, leur traduction",
    "Traduire l'ensemble de la phrase en français",
    "Analyser et traduire chaque mot individuellement",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def decouper_phrases(texte):
    phrases = re.split(r'[.?!;]+', texte)
    phrases = [p.strip() for p in phrases if len(p.split()) >= 3]
    return phrases


def nettoyer_json(content):
    content = content.strip()
    content = re.sub(r'^```json\s*', '', content)
    content = re.sub(r'^```\s*', '', content)
    content = re.sub(r'\s*```$', '', content)
    return content.strip()


def null_si_vide(val):
    if val is None or val == 'null' or val == '':
        return None
    return val


def _chunks_texte(texte, max_chars=800):
    """Découpe le texte en blocs bornés (≤ max_chars), sur les frontières de phrase.

    Évite d'envoyer un texte trop long en un seul appel : la réponse JSON de Claude
    serait tronquée/malformée à max_tokens. Coupe aussi à l'intérieur d'une longue
    séquence sans ponctuation (sur les espaces) pour garantir la borne."""
    parts = re.split(r'(?<=[.?!;:])\s+', texte.strip())
    # Borne dure : casse toute séquence plus longue que max_chars sur un espace.
    atoms = []
    for p in (s.strip() for s in parts):
        while len(p) > max_chars:
            cut = p.rfind(' ', 0, max_chars)
            if cut <= 0:
                cut = max_chars
            atoms.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            atoms.append(p)
    chunks, cur = [], ''
    for a in atoms:
        if cur and len(cur) + len(a) + 1 > max_chars:
            chunks.append(cur)
            cur = a
        else:
            cur = (cur + ' ' + a).strip()
    if cur:
        chunks.append(cur)
    return chunks


def _coerce_liste_mots(data):
    """Normalise la sortie de Claude en liste de dicts (mots).

    Claude renvoie parfois la liste enveloppée dans un objet ({"mots": [...]}),
    ou un seul objet, ou des éléments parasites. On ne garde que les dicts."""
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                data = v
                break
        else:
            data = [data]
    if not isinstance(data, list):
        return []
    return [m for m in data if isinstance(m, dict)]


def _extraire_vocab_bloc(texte):
    prompt = (
        "Analyse ce texte latin et retourne uniquement un JSON valide (sans balises markdown) "
        "contenant un tableau de tous les mots significatifs "
        "(exclure : conjonctions courantes, mots trop ambigus). "
        "Pour chaque mot retourne exactement ces champs :\n"
        '{\n'
        '  "forme": "forme telle qu\'elle apparaît dans le texte",\n'
        '  "lemme": "forme canonique du dictionnaire",\n'
        '  "categorie": "nom|verbe|adjectif|préposition|adverbe|pronom",\n'
        '  "cas": "nominatif|génitif|datif|accusatif|ablatif|vocatif|null",\n'
        '  "temps": "présent|imparfait|parfait|plus-que-parfait|futur|null",\n'
        '  "mode": "indicatif|subjonctif|infinitif|impératif|participe|null",\n'
        '  "personne": "1|2|3|null",\n'
        '  "nombre": "singulier|pluriel|null",\n'
        '  "traduction_fr": "traduction française",\n'
        '  "phrase_contexte": "phrase latine complète d\'où est extrait ce mot"\n'
        '}\n'
        f'Texte latin : {texte}'
    )
    content = nettoyer_json(appeler_claude(prompt, temperature=0.2, max_tokens=8000,
                                           system=SYSTEM_EXTRACTION))
    return _coerce_liste_mots(json.loads(content))


def extraire_vocabulaire_gpt(texte):
    """Extrait le vocabulaire en traitant le texte par blocs pour éviter la troncature."""
    mots = []
    for bloc in _chunks_texte(texte):
        mots.extend(_extraire_vocab_bloc(bloc))
    return mots


# ── Routes principales ────────────────────────────────────────────────────────

@app.route('/api/usage')
def api_usage():
    return jsonify(_charger_usage())


@app.route('/')
def index():
    textes = db.get_textes()
    return render_template('index.html', textes=textes)


@app.route('/upload', methods=['POST'])
def upload():
    titre = request.form.get('titre', '').strip()
    auteur = request.form.get('auteur', '').strip() or None

    if not titre:
        return jsonify({'error': 'Le titre est requis.'}), 400

    contenu = ''
    if 'fichier' in request.files and request.files['fichier'].filename:
        fichier = request.files['fichier']
        if not fichier.filename.lower().endswith('.txt'):
            return jsonify({'error': 'Seuls les fichiers .txt sont acceptés.'}), 400
        try:
            contenu = fichier.read().decode('utf-8')
        except UnicodeDecodeError:
            return jsonify({'error': 'Impossible de lire le fichier (encodage non-UTF-8).'}), 400
    else:
        contenu = request.form.get('contenu', '').strip()

    if not contenu:
        return jsonify({'error': 'Le contenu du texte est requis.'}), 400

    try:
        texte_id = db.insert_texte(titre, auteur, contenu)
        phrases = decouper_phrases(contenu)

        if not phrases:
            db.delete_texte(texte_id)
            return jsonify({'error': 'Aucune phrase valide trouvée (minimum 3 mots par phrase).'}), 400

        phrase_ids = db.insert_phrases(texte_id, phrases)

        mots_gpt = extraire_vocabulaire_gpt(contenu)

        mots_to_insert = []
        for mot in mots_gpt:
            contexte = mot.get('phrase_contexte', '')
            phrase_id = None
            for phrase, pid in zip(phrases, phrase_ids):
                if phrase in contexte or contexte in phrase:
                    phrase_id = pid
                    break

            mots_to_insert.append({
                'texte_id': texte_id,
                'phrase_id': phrase_id,
                'forme': mot.get('forme'),
                'lemme': mot.get('lemme'),
                'categorie': null_si_vide(mot.get('categorie')),
                'cas': null_si_vide(mot.get('cas')),
                'temps': null_si_vide(mot.get('temps')),
                'mode': null_si_vide(mot.get('mode')),
                'personne': null_si_vide(mot.get('personne')),
                'nombre': null_si_vide(mot.get('nombre')),
                'traduction_fr': mot.get('traduction_fr'),
                'contexte': contexte or None,
            })

        if mots_to_insert:
            db.insert_mots(mots_to_insert)

        return jsonify({'success': True, 'texte_id': texte_id, 'redirect': f'/trainer/{texte_id}'})

    except json.JSONDecodeError as e:
        db.delete_texte(texte_id)
        return jsonify({'error': f'Réponse IA invalide (JSON malformé) : {e}'}), 500
    except Exception as e:
        return jsonify({'error': f'Erreur serveur : {e}'}), 500


# ── Trainer ───────────────────────────────────────────────────────────────────

@app.route('/trainer/<int:texte_id>')
def trainer(texte_id):
    texte = db.get_texte(texte_id)
    if not texte:
        return redirect(url_for('index'))
    phrases = db.get_phrases(texte_id)
    if not phrases:
        return redirect(url_for('index'))
    return render_template('trainer.html', texte=texte, phrases=phrases, etapes=ETAPES)


@app.route('/evaluate', methods=['POST'])
def evaluate():
    data = request.json or {}
    phrase = data.get('phrase', '').strip()
    etape_index = int(data.get('etape_index', 0))
    reponse_utilisateur = data.get('reponse', '').strip()
    nb_tentatives = int(data.get('nb_tentatives', 1))
    abandon = bool(data.get('abandon', False))

    if not phrase or not reponse_utilisateur:
        return jsonify({'error': 'Données manquantes.'}), 400

    if 0 <= etape_index < len(ETAPES):
        etape_label = ETAPES[etape_index]
    else:
        etape_label = "Analyse générale"

    if abandon:
        nb_tentatives = 3

    try:
        prompt = (
            f"Phrase latine : {phrase}\n"
            f"Étape demandée : {etape_label}\n"
            f"Réponse de l'élève : {reponse_utilisateur}\n"
            f"Nombre de tentatives : {nb_tentatives}\n\n"
            "Instructions selon le nombre de tentatives :\n"
            "- tentatives == 1 : évalue et si incorrect, donne un indice vague\n"
            "- tentatives == 2 : évalue et si incorrect, donne un indice plus précis\n"
            "- tentatives >= 3 : donne la réponse complète avec explication pédagogique\n\n"
            "Réponds uniquement en JSON valide (sans balises markdown) :\n"
            '{"correct": true/false, "feedback": "message à afficher", '
            '"reponse_complete": "..." ou null}'
        )

        content = nettoyer_json(appeler_claude(prompt, temperature=0.5, max_tokens=1000,
                                               system=SYSTEM_TRAINER))
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            m = re.search(r'\{.*\}', content, re.DOTALL)
            result = json.loads(m.group(0)) if m else {}
        return jsonify(result)

    except json.JSONDecodeError as e:
        return jsonify({'error': f'Réponse IA invalide : {e}', 'correct': False,
                        'feedback': 'Erreur lors de l\'évaluation, veuillez réessayer.',
                        'reponse_complete': None}), 500
    except Exception as e:
        return jsonify({'error': str(e), 'correct': False,
                        'feedback': 'Erreur serveur, veuillez réessayer.',
                        'reponse_complete': None}), 500


# ── Corpus ────────────────────────────────────────────────────────────────────

@app.route('/corpus')
def corpus():
    textes = db.get_textes()
    return render_template('corpus.html', textes=textes)


@app.route('/corpus/mots')
def corpus_mots():
    texte_id = request.args.get('texte_id', type=int)
    categorie = request.args.get('categorie') or None
    mots = db.get_mots(texte_id=texte_id, categorie=categorie)
    return jsonify(mots)


@app.route('/corpus/export')
def corpus_export():
    texte_id = request.args.get('texte_id', type=int)
    categorie = request.args.get('categorie') or None
    mots = db.get_mots(texte_id=texte_id, categorie=categorie)

    fields = ['id', 'forme', 'lemme', 'categorie', 'cas', 'temps',
              'mode', 'personne', 'nombre', 'traduction_fr', 'contexte', 'texte_titre']

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for mot in mots:
        writer.writerow({f: mot.get(f, '') or '' for f in fields})

    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=corpus_latin.csv'},
    )


@app.route('/corpus/<int:texte_id>', methods=['DELETE'])
def delete_corpus(texte_id):
    try:
        db.delete_texte(texte_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Quiz ──────────────────────────────────────────────────────────────────────

@app.route('/quiz')
def quiz():
    textes = db.get_textes()
    return render_template('quiz.html', textes=textes)


@app.route('/quiz/start', methods=['POST'])
def quiz_start():
    data = request.json or {}
    types_quiz = data.get('types') or ['latin_fr']
    nb_questions = min(int(data.get('nb_questions', 10)), 50)
    categorie = data.get('categorie') or None

    texte_id = data.get('texte_id')
    if not texte_id:
        texte_id = None
    else:
        try:
            texte_id = int(texte_id)
        except (ValueError, TypeError):
            texte_id = None

    mots = db.get_mots_for_quiz(texte_id=texte_id, categorie=categorie, limit=nb_questions * 4)

    if not mots:
        return jsonify({'error': 'Corpus vide. Uploadez d\'abord un texte pour commencer un quiz.'}), 400

    random.shuffle(mots)
    questions = []

    for i, mot in enumerate(mots):
        if len(questions) >= nb_questions:
            break

        type_q = random.choice(types_quiz)

        if type_q == 'latin_fr':
            if not mot.get('traduction_fr'):
                continue
            questions.append({
                'id': i, 'type': 'latin_fr', 'mot_id': mot['id'],
                'question': f'Que signifie : « {mot["forme"]} » ?',
                'reponse_attendue': mot['traduction_fr'],
            })

        elif type_q == 'fr_latin':
            if not mot.get('traduction_fr'):
                continue
            questions.append({
                'id': i, 'type': 'fr_latin', 'mot_id': mot['id'],
                'question': f'Comment dit-on en latin : « {mot["traduction_fr"]} » ?',
                'reponse_attendue': mot['forme'],
            })

        elif type_q == 'forme_analyse':
            questions.append({
                'id': i, 'type': 'forme_analyse', 'mot_id': mot['id'],
                'question': f'Analysez la forme : « {mot["forme"]} »',
                'reponse_attendue': {
                    'categorie': mot.get('categorie'),
                    'cas': mot.get('cas'),
                    'temps': mot.get('temps'),
                    'mode': mot.get('mode'),
                    'personne': mot.get('personne'),
                    'nombre': mot.get('nombre'),
                },
            })

        elif type_q == 'lacunaire':
            contexte = mot.get('contexte') or ''
            forme = mot.get('forme', '')
            if not contexte or not forme or forme not in contexte:
                # fallback
                if mot.get('traduction_fr'):
                    questions.append({
                        'id': i, 'type': 'latin_fr', 'mot_id': mot['id'],
                        'question': f'Que signifie : « {forme} » ?',
                        'reponse_attendue': mot['traduction_fr'],
                    })
                continue

            lacune = contexte.replace(forme, '▢' * len(forme), 1)
            indice_parts = []
            if mot.get('categorie'):
                indice_parts.append(mot['categorie'])
            if mot.get('cas'):
                indice_parts.append(f"cas : {mot['cas']}")
            if mot.get('nombre'):
                indice_parts.append(mot['nombre'])
            if mot.get('temps'):
                indice_parts.append(mot['temps'])
            indice = ', '.join(indice_parts) if indice_parts else 'mot latin'

            questions.append({
                'id': i, 'type': 'lacunaire', 'mot_id': mot['id'],
                'question': f'Complétez la phrase : « {lacune} »',
                'indice': f'(indice : {indice})',
                'reponse_attendue': forme,
            })

        else:
            if mot.get('traduction_fr'):
                questions.append({
                    'id': i, 'type': 'latin_fr', 'mot_id': mot['id'],
                    'question': f'Que signifie : « {mot["forme"]} » ?',
                    'reponse_attendue': mot['traduction_fr'],
                })

    if not questions:
        return jsonify({'error': 'Impossible de générer des questions avec les critères choisis.'}), 400

    return jsonify({'questions': questions[:nb_questions]})


def _normaliser_reponse(s):
    """Minuscule, sans accents, sans ponctuation ni article initial."""
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode()
    s = s.lower().strip()
    s = re.sub(r"^(le |la |les |l'|un |une |des |du |de la |de |d')", '', s)
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def _reponses_equivalentes(donnee, attendue):
    """Vrai si la réponse correspond à l'attendue (ou à l'une de ses variantes
    séparées par , / ;) après normalisation."""
    if not isinstance(attendue, str):
        return False
    d = _normaliser_reponse(donnee)
    if not d:
        return False
    variantes = re.split(r'[,;/]| ou ', attendue)
    return any(d == _normaliser_reponse(v) for v in variantes if v.strip())


@app.route('/quiz/evaluate', methods=['POST'])
def quiz_evaluate():
    data = request.json or {}
    type_quiz = data.get('type', '')
    reponse_utilisateur = data.get('reponse')
    reponse_attendue = data.get('reponse_attendue')
    question = data.get('question', '')
    mot_id = data.get('mot_id')
    temps = int(data.get('temps', 0))

    if type_quiz == 'forme_analyse':
        if not isinstance(reponse_attendue, dict) or not isinstance(reponse_utilisateur, dict):
            return jsonify({'error': 'Format invalide pour forme_analyse'}), 400

        score = 0
        total = 0
        details = []
        labels = {
            'categorie': 'Catégorie', 'cas': 'Cas', 'temps': 'Temps',
            'mode': 'Mode', 'personne': 'Personne', 'nombre': 'Nombre',
        }
        for key in ['categorie', 'cas', 'temps', 'mode', 'personne', 'nombre']:
            attendu = reponse_attendue.get(key)
            if not attendu:
                continue
            total += 1
            donne = (reponse_utilisateur.get(key) or '').strip().lower()
            if donne == attendu.lower():
                score += 1
                details.append(f"✓ {labels[key]} : {attendu}")
            else:
                details.append(f"✗ {labels[key]} : attendu « {attendu} », donné « {donne or '—'} »")

        correct = (total > 0 and score == total)
        feedback = f"Score : {score}/{total}\n" + "\n".join(details)

        db.insert_quiz_resultat(type_quiz, mot_id, str(reponse_utilisateur), correct, temps)
        return jsonify({'correct': correct, 'feedback': feedback, 'reponse_correcte': reponse_attendue})

    # Types ①②④ : réponse texte

    # Voie rapide : correspondance locale (accents/casse/articles ignorés) → instantané,
    # sans appel Claude. La grande majorité des bonnes réponses passent par ici.
    if _reponses_equivalentes(reponse_utilisateur, reponse_attendue):
        db.insert_quiz_resultat(type_quiz, mot_id, str(reponse_utilisateur), True, temps)
        return jsonify({'correct': True, 'feedback': 'Correct ! 🎉',
                        'reponse_correcte': reponse_attendue})

    # Évaluation différée : on ne dérange pas Claude maintenant, la réponse sera
    # corrigée en un seul appel groupé en fin de quiz (cf. /quiz/evaluate/batch).
    if data.get('defer'):
        return jsonify({'pending': True})

    # Sinon : évaluation Claude (tolérance synonymes / fautes légères)
    try:
        prompt = (
            f"Question posée : {question}\n"
            f"Réponse attendue : {reponse_attendue}\n"
            f"Réponse de l'élève : {reponse_utilisateur}\n\n"
            "Évalue si la réponse de l'élève est correcte. Sois tolérant sur :\n"
            "- les fautes d'orthographe légères\n"
            "- les synonymes acceptables\n"
            "- les variations mineures de forme\n\n"
            "Réponds uniquement en JSON valide :\n"
            '{"correct": true/false, "feedback": "explication courte et encourageante"}'
        )

        content = nettoyer_json(appeler_claude(prompt, temperature=0.3, max_tokens=1000,
                                               system=SYSTEM_CORRECTION))
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            # Repli : extraire le 1er objet JSON présent dans la réponse
            m = re.search(r'\{.*\}', content, re.DOTALL)
            result = json.loads(m.group(0)) if m else {}
        correct = bool(result.get('correct', False))
        feedback = result.get('feedback', '') or (
            'Correct !' if correct else f"Réponse attendue : {reponse_attendue}")

        db.insert_quiz_resultat(type_quiz, mot_id, str(reponse_utilisateur), correct, temps)
        return jsonify({'correct': correct, 'feedback': feedback, 'reponse_correcte': reponse_attendue})

    except Exception as e:
        # Ne jamais rester silencieux : feedback explicite côté élève
        return jsonify({'error': f'Erreur d\'évaluation : {e}',
                        'correct': False,
                        'feedback': "Impossible de joindre l'IA. Réessaie dans un instant.",
                        'reponse_correcte': reponse_attendue}), 200


@app.route('/quiz/evaluate/batch', methods=['POST'])
def quiz_evaluate_batch():
    """Corrige plusieurs réponses en UN seul appel Claude (fin de quiz).

    Les correspondances exactes sont tranchées en local (0 token) ; seules les
    réponses approximatives partent à Claude, regroupées → économie de tokens."""
    data = request.json or {}
    items = data.get('items', [])
    resultats = [None] * len(items)
    a_evaluer = []  # [(index_global, item)]

    for i, it in enumerate(items):
        rep = it.get('reponse')
        att = it.get('reponse_attendue')
        temps = int(it.get('temps', 0))
        if _reponses_equivalentes(rep, att):
            resultats[i] = {'correct': True, 'feedback': 'Correct ! 🎉'}
            db.insert_quiz_resultat(it.get('type', ''), it.get('mot_id'), str(rep), True, temps)
        else:
            a_evaluer.append((i, it))

    if a_evaluer:
        try:
            lignes = []
            for n, (_, it) in enumerate(a_evaluer):
                lignes.append(f'{n}. Question : {it.get("question", "")} | '
                              f'Attendu : {it.get("reponse_attendue")} | '
                              f'Élève : {it.get("reponse")}')
            prompt = (
                "Corrige ce quiz de latin. Pour chaque numéro, indique si la réponse de "
                "l'élève est correcte (tolère fautes légères, synonymes, variantes mineures) "
                "et donne un feedback très court et encourageant.\n"
                "Réponds uniquement par un tableau JSON, un objet par numéro, dans l'ordre :\n"
                '[{"n":0,"correct":true,"feedback":"…"}]\n\n'
                + "\n".join(lignes)
            )
            content = nettoyer_json(appeler_claude(prompt, temperature=0.2, max_tokens=1500,
                                                   system=SYSTEM_CORRECTION))
            try:
                arr = json.loads(content)
            except json.JSONDecodeError:
                m = re.search(r'\[.*\]', content, re.DOTALL)
                arr = json.loads(m.group(0)) if m else []
            verdicts = {int(o['n']): o for o in arr
                        if isinstance(o, dict) and 'n' in o} if isinstance(arr, list) else {}
        except Exception:
            verdicts = {}

        for n, (i, it) in enumerate(a_evaluer):
            v = verdicts.get(n, {})
            correct = bool(v.get('correct', False))
            feedback = v.get('feedback') or (
                'Correct !' if correct else f"Réponse attendue : {it.get('reponse_attendue')}")
            resultats[i] = {'correct': correct, 'feedback': feedback}
            db.insert_quiz_resultat(it.get('type', ''), it.get('mot_id'),
                                    str(it.get('reponse')), correct, int(it.get('temps', 0)))

    return jsonify({'results': resultats})


@app.route('/quiz/historique')
def quiz_historique():
    historique = db.get_quiz_historique()
    return jsonify(historique)


if __name__ == '__main__':
    db.init_db()
    port = int(os.getenv('PORT', 5002))
    print(f"Latin Trainer démarré sur http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
