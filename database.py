import sqlite3

DB_PATH = 'latin_trainer.db'


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS textes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titre TEXT NOT NULL,
            auteur TEXT,
            contenu TEXT NOT NULL,
            date_ajout DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS phrases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            texte_id INTEGER REFERENCES textes(id) ON DELETE CASCADE,
            ordre INTEGER,
            contenu TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS mots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            texte_id INTEGER REFERENCES textes(id) ON DELETE CASCADE,
            phrase_id INTEGER REFERENCES phrases(id),
            forme TEXT NOT NULL,
            lemme TEXT,
            categorie TEXT,
            cas TEXT,
            temps TEXT,
            mode TEXT,
            personne TEXT,
            nombre TEXT,
            traduction_fr TEXT,
            contexte TEXT
        );

        CREATE TABLE IF NOT EXISTS quiz_resultats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_quiz DATETIME DEFAULT CURRENT_TIMESTAMP,
            type_quiz TEXT,
            mot_id INTEGER REFERENCES mots(id),
            reponse_utilisateur TEXT,
            correct BOOLEAN,
            temps_reponse_sec INTEGER
        );
    ''')
    conn.commit()
    conn.close()


# ── Textes ────────────────────────────────────────────────────────────────────

def insert_texte(titre, auteur, contenu):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO textes (titre, auteur, contenu) VALUES (?, ?, ?)",
        (titre, auteur, contenu)
    )
    texte_id = cur.lastrowid
    conn.commit()
    conn.close()
    return texte_id


def get_textes():
    conn = get_db()
    rows = conn.execute('''
        SELECT t.*,
               COUNT(DISTINCT p.id) AS nb_phrases,
               COUNT(DISTINCT m.id) AS nb_mots
        FROM textes t
        LEFT JOIN phrases p ON p.texte_id = t.id
        LEFT JOIN mots m ON m.texte_id = t.id
        GROUP BY t.id
        ORDER BY t.date_ajout DESC
    ''').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_texte(texte_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM textes WHERE id = ?", (texte_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_texte(texte_id):
    conn = get_db()
    conn.execute("DELETE FROM textes WHERE id = ?", (texte_id,))
    conn.commit()
    conn.close()


# ── Phrases ───────────────────────────────────────────────────────────────────

def insert_phrases(texte_id, phrases):
    conn = get_db()
    ids = []
    for i, p in enumerate(phrases):
        cur = conn.execute(
            "INSERT INTO phrases (texte_id, ordre, contenu) VALUES (?, ?, ?)",
            (texte_id, i, p)
        )
        ids.append(cur.lastrowid)
    conn.commit()
    conn.close()
    return ids


def get_phrases(texte_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM phrases WHERE texte_id = ? ORDER BY ordre",
        (texte_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Mots ──────────────────────────────────────────────────────────────────────

def insert_mots(mots_data):
    conn = get_db()
    conn.executemany('''
        INSERT INTO mots
            (texte_id, phrase_id, forme, lemme, categorie, cas, temps,
             mode, personne, nombre, traduction_fr, contexte)
        VALUES
            (:texte_id, :phrase_id, :forme, :lemme, :categorie, :cas, :temps,
             :mode, :personne, :nombre, :traduction_fr, :contexte)
    ''', mots_data)
    conn.commit()
    conn.close()


def get_mots(texte_id=None, categorie=None):
    conn = get_db()
    query = '''
        SELECT m.*, t.titre AS texte_titre
        FROM mots m
        JOIN textes t ON t.id = m.texte_id
        WHERE 1=1
    '''
    params = []
    if texte_id:
        query += " AND m.texte_id = ?"
        params.append(texte_id)
    if categorie:
        query += " AND m.categorie = ?"
        params.append(categorie)
    query += " ORDER BY m.id"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_mots_for_quiz(texte_id=None, categorie=None, limit=150):
    conn = get_db()
    query = "SELECT * FROM mots WHERE forme IS NOT NULL AND traduction_fr IS NOT NULL"
    params = []
    if texte_id:
        query += " AND texte_id = ?"
        params.append(texte_id)
    if categorie:
        query += " AND categorie = ?"
        params.append(categorie)
    query += " ORDER BY RANDOM() LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_mots():
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM mots").fetchone()[0]
    conn.close()
    return count


# ── Quiz résultats ────────────────────────────────────────────────────────────

def insert_quiz_resultat(type_quiz, mot_id, reponse, correct, temps):
    conn = get_db()
    conn.execute('''
        INSERT INTO quiz_resultats
            (type_quiz, mot_id, reponse_utilisateur, correct, temps_reponse_sec)
        VALUES (?, ?, ?, ?, ?)
    ''', (type_quiz, mot_id, str(reponse), int(bool(correct)), int(temps or 0)))
    conn.commit()
    conn.close()


def get_quiz_historique(limit=50):
    conn = get_db()
    rows = conn.execute('''
        SELECT
            date(date_quiz)   AS jour,
            type_quiz,
            COUNT(*)          AS nb_questions,
            SUM(correct)      AS nb_correct
        FROM quiz_resultats
        GROUP BY date(date_quiz), type_quiz
        ORDER BY jour DESC
        LIMIT ?
    ''', (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
