from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy #for sqlite
from sqlalchemy.exc import OperationalError
import pandas as pd
import sqlite3
import json
import os
import random
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key'

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///responses.db' #for sqlite
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False #for sqlite
db = SQLAlchemy(app) #for sqlite



###define database models for sqlite
class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    prolific_id = db.Column(db.String(64), unique=True, nullable=False)
    condition = db.Column(db.String(32))
    timestamp_start = db.Column(db.DateTime)
    demographics = db.Column(db.JSON)
    pre_questionnaire = db.Column(db.JSON)
    post_questionnaire = db.Column(db.JSON)
    rounds = db.relationship('Round', backref='participant', lazy=True)

class Round(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    round_number = db.Column(db.Integer)
    participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=False)
    theme_selection = db.Column(db.JSON)
    article = db.Column(db.JSON)
    mid_questionnaire = db.Column(db.JSON)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    # Flattened rating-box fields (2 recommendations)
    main_article_stable_id = db.Column(db.String)
    main_article_title = db.Column(db.String)

    rec0_stable_id = db.Column(db.String)
    rec0_title = db.Column(db.String)
    rec0_likelihood = db.Column(db.Integer)
    rec0_constructive = db.Column(db.Integer)
    rec0_understandable = db.Column(db.Integer)
    rec0_trustworthy = db.Column(db.Integer)
    rec0_relevant = db.Column(db.Integer)

    rec1_stable_id = db.Column(db.String)
    rec1_title = db.Column(db.String)
    rec1_likelihood = db.Column(db.Integer)
    rec1_constructive = db.Column(db.Integer)
    rec1_understandable = db.Column(db.Integer)
    rec1_trustworthy = db.Column(db.Integer)
    rec1_relevant = db.Column(db.Integer)

    label_understandable = db.Column(db.Integer)
    label_useful = db.Column(db.Integer)
    label_influenced = db.Column(db.Integer)
    label_attention = db.Column(db.Integer)
    label_more = db.Column(db.Integer)
###


# Ensure response tables exist (responses.db) without requiring manual migrations.
# Must be called after models are declared.
with app.app_context():
    db.create_all()


def _ensure_round_flat_columns():
    """Lightweight SQLite migration: add missing flattened columns to `round`.

    SQLite doesn't support full ALTER COLUMN migrations, but it *does* support
    `ALTER TABLE ... ADD COLUMN ...`, which is enough for our appended columns.
    """
    engine = db.engine
    with engine.connect() as conn:
        try:
            existing_cols = {
                row[1]
                for row in conn.exec_driver_sql('PRAGMA table_info("round")').all()
            }
        except Exception:
            # If the table doesn't exist yet, create_all() above will handle it.
            return

        desired_cols = {
            'main_article_stable_id': 'TEXT',
            'main_article_title': 'TEXT',
            'rec0_stable_id': 'TEXT',
            'rec0_title': 'TEXT',
            'rec0_likelihood': 'INTEGER',
            'rec0_constructive': 'INTEGER',
            'rec0_understandable': 'INTEGER',
            'rec0_trustworthy': 'INTEGER',
            'rec0_relevant': 'INTEGER',
            'rec1_stable_id': 'TEXT',
            'rec1_title': 'TEXT',
            'rec1_likelihood': 'INTEGER',
            'rec1_constructive': 'INTEGER',
            'rec1_understandable': 'INTEGER',
            'rec1_trustworthy': 'INTEGER',
            'rec1_relevant': 'INTEGER',
            'label_understandable': 'INTEGER',
            'label_useful': 'INTEGER',
            'label_influenced': 'INTEGER',
            'label_attention': 'INTEGER',
            'label_more': 'INTEGER',
        }

        for col_name, col_type in desired_cols.items():
            if col_name in existing_cols:
                continue
            conn.exec_driver_sql(f'ALTER TABLE "round" ADD COLUMN {col_name} {col_type}')


with app.app_context():
    _ensure_round_flat_columns()


RESPONSES_DIR = "responses"
os.makedirs(RESPONSES_DIR, exist_ok=True)

@app.before_request
def setup_session_and_redirects():
    pid = request.args.get('PROLIFIC_PID')
    if pid:
        session['prolific_id'] = pid

    allowed_routes = {'landing', 'static'}

    # Redirect to landing if no Prolific ID
    if not session.get('prolific_id') and request.endpoint not in allowed_routes:
        return redirect(url_for('landing'))



def require_previous_step(step_name):
    def wrapper(f):
        def decorated_function(*args, **kwargs):
            if not session.get(f'{step_name}_completed', False):
                return redirect(url_for(step_name))
            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__
        return decorated_function
    return wrapper

@app.route('/set-condition/<cond>')
def set_condition(cond):
    if cond in ['color', 'no_color', 'c2pa', 'nolabel']:
        session['condition'] = cond
        return f"Condition set to {cond}. <a href='/select-article'>Continue</a>"
    return "Invalid condition", 400


# Load articles from SQLite database

ARTICLES_DB_PATH = "articles_cleaned_new.db"
conn = sqlite3.connect(ARTICLES_DB_PATH)
raw_df = pd.read_sql_query("SELECT * FROM new_articles", conn)
conn.close()

# The first row contains the actual headers
headers = list(raw_df.iloc[0])
raw_df = raw_df[1:].copy()
raw_df.columns = [str(h).strip() for h in headers]

# Pick topic/category column
if 'field20' in raw_df.columns:
    # Study uses field20 as the canonical topic column.
    TOPIC_COL = 'field20'
elif 'topic' in raw_df.columns:
    TOPIC_COL = 'topic'
elif 'Category' in raw_df.columns:
    TOPIC_COL = 'Category'
elif '_cached_topics' in raw_df.columns:
    TOPIC_COL = '_cached_topics'
else:
    nunique = raw_df.nunique(dropna=True)
    small_cols = [c for c in raw_df.columns if 1 < nunique.get(c, 0) <= 50]
    TOPIC_COL = small_cols[0] if small_cols else raw_df.columns[0]

df = raw_df.reset_index(drop=True).copy()
df.reset_index(inplace=True)
app.logger.info("Loaded articles from DB. Columns: %s", df.columns.tolist())
app.logger.info("Using topic column: %s", TOPIC_COL)


TOPIC_MAP_LIST_A = {
    'Business & Economics': 'Economics',
    'International News': 'International',
    'Crime': 'Crime',
    'Finance': 'Finance',
    'Politics': 'Politics',
    'Public Health & Health Policy': 'Health',
}

TOPIC_MAP_LIST_B = {
    'Lifestyle': 'Lifestyle',
    'Entertainment': 'Entertainment',
    'Science': 'Science',
    'Tech': 'Tech',
    'Sports': 'Sports',
    'Personal Health & Wellbeing': 'Health',
}


def _map_list_topic(list_name: str, selection: str | None) -> str | None:
    if not selection:
        return None
    mapping = TOPIC_MAP_LIST_A if list_name == 'A' else TOPIC_MAP_LIST_B
    return mapping.get(selection)


def _ensure_topic_start_list():
    """Pick and persist which list starts round 1 (A or B)."""
    if session.get('topic_start_list') in ('A', 'B'):
        return
    session['topic_start_list'] = random.choice(['A', 'B'])


def _list_for_round(round_number: int) -> str:
    """Alternate lists A/B by round, starting from randomized start list."""
    _ensure_topic_start_list()
    start = session.get('topic_start_list', 'A')
    if round_number % 2 == 1:
        return start
    return 'B' if start == 'A' else 'A'


def _normalize_topic_value(val) -> str:
    if val is None:
        return ''
    if isinstance(val, (list, tuple)):
        val = val[0] if val else ''
    return str(val).strip().lower()


def normalize_article_row(row_dict):
    """Map article row keys (from CSV) to the keys expected by templates.
    Templates expect keys like 'Title', 'Content', 'Image URL', 'Author', 'Date', and 'index'.
    This function is defensive about different column names and value formats.
    """
    out = {}
    # index (ensure int where possible)
    try:
        out['index'] = int(row_dict.get('index', row_dict.get('Index', 0)))
    except Exception:
        out['index'] = row_dict.get('index', row_dict.get('Index', 0))

    # Title
    out['Title'] = row_dict.get('Title') or row_dict.get('title') or row_dict.get('headline') or ''

    # Content / body
    out['Content'] = row_dict.get('Content') or row_dict.get('content') or ''

    # Image URL candidates: 'Image URL', 'image', 'media'
    out['Image URL'] = row_dict.get('Image URL') or row_dict.get('image') or row_dict.get('media') or row_dict.get('image_url') or ''

    # Author: try several fields and tidy lists stored as strings
    author = row_dict.get('Author') or row_dict.get('author') or ''
    if not author:
        authors = row_dict.get('authors') or row_dict.get('journalists') or ''
        if isinstance(authors, (list, tuple)):
            author = ', '.join(authors)
        elif isinstance(authors, str) and authors.startswith('[') and authors.endswith(']'):
            try:
                parsed = json.loads(authors)
                if isinstance(parsed, list):
                    author = ', '.join(parsed)
                else:
                    author = str(parsed)
            except Exception:
                author = authors
    out['Author'] = author or None

    # Date: prefer published_date then updated_date
    out['Date'] = row_dict.get('Date') or row_dict.get('published_date') or row_dict.get('updated_date') or ''

    # Keep any other original fields for debugging or downstream use
    for k, v in row_dict.items():
        if k not in out:
            out[k] = v

    return out


def get_stable_article_id(article_row: dict):
    """Return a stable identifier from the articles DB row.

    The `new_articles` table uses generic column names (field1, field2, ...),
    but the first data-row is treated as headers in this app.
    We prefer `internal_id` if present, otherwise fall back to `field1`.
    """
    if not isinstance(article_row, dict):
        return None
    return article_row.get('internal_id') or article_row.get('Internal ID') or article_row.get('field1')


@app.route('/debug-init-db')
def debug_init_db():
    """Diagnostics: initialize responses DB tables and report status."""
    with app.app_context():
        db.create_all()

    try:
        engine = db.engine
        db_path = None
        try:
            db_path = engine.url.database
        except Exception:
            db_path = None

        with engine.connect() as conn:
            rows = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").all()
        tables = [r[0] for r in rows]
    except Exception as e:
        return {'error': 'Failed to inspect DB', 'details': str(e)}, 500

    return {
        'db_uri': app.config.get('SQLALCHEMY_DATABASE_URI'),
        'db_path': db_path,
        'tables': tables,
        'hint': 'Expect to see participant and round tables.'
    }


@app.route('/debug-articles')
def debug_articles():
    """Quick diagnostics: returns detected columns, topic column, and a small sample of rows."""
    try:
        sample = df.head(5).to_dict(orient='records')
    except Exception:
        sample = []
    return {
        'columns': list(df.columns),
        'topic_col': TOPIC_COL,
        'sample_rows': sample
    }


@app.route('/debug-article/<int:article_id>')
def debug_article(article_id: int):
    """Diagnostics: look up a single article by its internal id (df['index']).

    This is the same id saved in responses under:
    - round.article.main_article_id
    - round.article.recommendations[]
    """
    row = df[df['index'] == article_id]
    if row.empty:
        return {
            'found': False,
            'article_id': article_id,
            'hint': "This app uses df['index'] (after reset_index) as the article id.",
        }, 404

    record = normalize_article_row(row.iloc[0].to_dict())
    return {
        'found': True,
        'article_id': int(record.get('index')),
        'stable_id': get_stable_article_id(record),
        'title': record.get('Title'),
        'author': record.get('Author'),
        'date': record.get('Date'),
        'topic_col': TOPIC_COL,
        'topic_value': record.get(TOPIC_COL),
    }


@app.route('/debug-rounds')
def debug_rounds():
    """Diagnostics: return participant + rounds saved so far.

    Usage:
    - Visit after or during a session: /debug-rounds
    - Or specify a pid: /debug-rounds?pid=PROLIFIC_PID
    """
    pid = request.args.get('pid') or session.get('prolific_id')
    if not pid:
        return {'error': 'No pid provided and no session prolific_id.'}, 400

    try:
        participant = Participant.query.filter_by(prolific_id=pid).first()
        if not participant:
            return {'pid': pid, 'participant': None, 'rounds': []}

        rounds = (
            Round.query.filter_by(participant_id=participant.id)
            .order_by(Round.round_number.asc())
            .all()
        )
    except OperationalError as e:
        # Typically indicates tables were never created ("no such table: participant").
        return {
            'error': 'Responses database tables are not initialized.',
            'hint': 'Restart the server after enabling db.create_all(), or delete responses.db to re-create it.',
            'details': str(e),
        }, 500

    def _to_dict_round(r: Round):
        return {
            'id': r.id,
            'round_number': r.round_number,
            'theme_selection': r.theme_selection,
            'article': r.article,
            'mid_questionnaire': r.mid_questionnaire,
            'timestamp': r.timestamp.isoformat() if r.timestamp else None,
        }

    return {
        'pid': pid,
        'participant': {
            'id': participant.id,
            'prolific_id': participant.prolific_id,
            'condition': participant.condition,
            'timestamp_start': participant.timestamp_start.isoformat() if participant.timestamp_start else None,
            'demographics': participant.demographics,
            'pre_questionnaire': participant.pre_questionnaire,
            'post_questionnaire': participant.post_questionnaire,
        },
        'rounds': [_to_dict_round(r) for r in rounds],
    }


@app.route('/debug-backfill-flat')
def debug_backfill_flat():
    """Diagnostics: backfill flattened round columns from stored JSON.

    Usage:
    - Backfill all rounds: /debug-backfill-flat
    - Backfill only one participant: /debug-backfill-flat?pid=PROLIFIC_PID
    """
    pid = request.args.get('pid')
    q = Round.query
    participant = None
    if pid:
        participant = Participant.query.filter_by(prolific_id=pid).first()
        if not participant:
            return {'error': 'Unknown pid', 'pid': pid}, 404
        q = q.filter_by(participant_id=participant.id)

    rounds = q.order_by(Round.id.asc()).all()
    updated = 0

    def _to_int(val):
        if val is None:
            return None
        if isinstance(val, int):
            return val
        try:
            s = str(val).strip()
            return int(s) if s else None
        except Exception:
            return None

    for r in rounds:
        payload = r.article if isinstance(r.article, dict) else None
        if not isinstance(payload, dict):
            continue

        r.main_article_stable_id = payload.get('main_article_stable_id')
        r.main_article_title = payload.get('main_article_title')

        rec_ids = payload.get('recommendations') or []
        rec_stable_ids = payload.get('recommendations_stable_ids') or []
        rec_titles = payload.get('recommendations_titles') or []
        ratings = payload.get('ratings') or {}

        def _rating_for_rec(rec_pos: int, key_prefix: str):
            rec_id = rec_ids[rec_pos] if len(rec_ids) > rec_pos else None
            if rec_id is not None:
                v = ratings.get(f'{key_prefix}_{rec_id}')
                if v not in (None, ''):
                    return v
            return ratings.get(f'{key_prefix}_{rec_pos}')

        r.rec0_stable_id = rec_stable_ids[0] if len(rec_stable_ids) > 0 else None
        r.rec0_title = rec_titles[0] if len(rec_titles) > 0 else None
        r.rec0_likelihood = _to_int(_rating_for_rec(0, 'likelihood'))
        r.rec0_constructive = _to_int(_rating_for_rec(0, 'constructive'))
        r.rec0_understandable = _to_int(_rating_for_rec(0, 'understandable'))
        r.rec0_trustworthy = _to_int(_rating_for_rec(0, 'trustworthy'))
        r.rec0_relevant = _to_int(_rating_for_rec(0, 'relevant'))

        r.rec1_stable_id = rec_stable_ids[1] if len(rec_stable_ids) > 1 else None
        r.rec1_title = rec_titles[1] if len(rec_titles) > 1 else None
        r.rec1_likelihood = _to_int(_rating_for_rec(1, 'likelihood'))
        r.rec1_constructive = _to_int(_rating_for_rec(1, 'constructive'))
        r.rec1_understandable = _to_int(_rating_for_rec(1, 'understandable'))
        r.rec1_trustworthy = _to_int(_rating_for_rec(1, 'trustworthy'))
        r.rec1_relevant = _to_int(_rating_for_rec(1, 'relevant'))

        r.label_understandable = _to_int(ratings.get('label_understandable'))
        r.label_useful = _to_int(ratings.get('label_useful'))
        r.label_influenced = _to_int(ratings.get('label_influenced'))
        r.label_attention = _to_int(ratings.get('label_attention'))
        r.label_more = _to_int(ratings.get('label_more'))

        updated += 1

    db.session.commit()
    return {
        'pid': pid,
        'participant_id': participant.id if participant else None,
        'rounds_seen': len(rounds),
        'rounds_updated': updated,
        'hint': 'Now query flattened columns from the `round` table.'
    }

def get_participant_id():
    return session.get('prolific_id')

def update_participant_data(section, data):
    pid = get_participant_id()
    if not pid:
        print("No Prolific PID found - skipping save.")
        return

    try:
        # Get or create participant
        participant = Participant.query.filter_by(prolific_id=pid).first()
        if not participant:
            participant = Participant(
                prolific_id=pid,
                timestamp_start=datetime.utcnow()
            )
            db.session.add(participant)
            db.session.flush()  # Assigns participant.id

        # Save section data
        if section == 'demographics':
            participant.demographics = data
        elif section == 'pre_questionnaire':
            participant.pre_questionnaire = data
        elif section == 'post_questionnaire':
            participant.post_questionnaire = data
        elif section == 'round':
            round_number = session.get('round', 1)
            existing_round = Round.query.filter_by(participant_id=participant.id, round_number=round_number).first()
            if not existing_round:
                existing_round = Round(
                    round_number=round_number,
                    participant_id=participant.id,
                    timestamp=datetime.utcnow()
                )
                db.session.add(existing_round)
                db.session.flush()

            def _to_int(val):
                if val is None:
                    return None
                if isinstance(val, int):
                    return val
                try:
                    s = str(val).strip()
                    return int(s) if s else None
                except Exception:
                    return None

            # Flatten rating-box data (if present)
            article_payload = data.get('article') if isinstance(data, dict) else None
            if isinstance(article_payload, dict):
                existing_round.main_article_stable_id = article_payload.get('main_article_stable_id')
                existing_round.main_article_title = article_payload.get('main_article_title')

                rec_stable_ids = article_payload.get('recommendations_stable_ids') or []
                rec_titles = article_payload.get('recommendations_titles') or []
                rec_ids = article_payload.get('recommendations') or []
                ratings = article_payload.get('ratings') or {}

                def _rating_for_rec(rec_pos: int, key_prefix: str):
                    """Get a rating value for a recommendation.

                    New data uses keys like: `${key_prefix}_${rec_id}` (because the form
                    names are based on rec.index). Some older code used `${key_prefix}_${pos}`.
                    """
                    rec_id = rec_ids[rec_pos] if len(rec_ids) > rec_pos else None
                    if rec_id is not None:
                        v = ratings.get(f'{key_prefix}_{rec_id}')
                        if v not in (None, ''):
                            return v
                    return ratings.get(f'{key_prefix}_{rec_pos}')

                # Recommendation 0
                existing_round.rec0_stable_id = rec_stable_ids[0] if len(rec_stable_ids) > 0 else None
                existing_round.rec0_title = rec_titles[0] if len(rec_titles) > 0 else None
                existing_round.rec0_likelihood = _to_int(_rating_for_rec(0, 'likelihood'))
                existing_round.rec0_constructive = _to_int(_rating_for_rec(0, 'constructive'))
                existing_round.rec0_understandable = _to_int(_rating_for_rec(0, 'understandable'))
                existing_round.rec0_trustworthy = _to_int(_rating_for_rec(0, 'trustworthy'))
                existing_round.rec0_relevant = _to_int(_rating_for_rec(0, 'relevant'))

                # Recommendation 1
                existing_round.rec1_stable_id = rec_stable_ids[1] if len(rec_stable_ids) > 1 else None
                existing_round.rec1_title = rec_titles[1] if len(rec_titles) > 1 else None
                existing_round.rec1_likelihood = _to_int(_rating_for_rec(1, 'likelihood'))
                existing_round.rec1_constructive = _to_int(_rating_for_rec(1, 'constructive'))
                existing_round.rec1_understandable = _to_int(_rating_for_rec(1, 'understandable'))
                existing_round.rec1_trustworthy = _to_int(_rating_for_rec(1, 'trustworthy'))
                existing_round.rec1_relevant = _to_int(_rating_for_rec(1, 'relevant'))

                # Label items (shared)
                existing_round.label_understandable = _to_int(ratings.get('label_understandable'))
                existing_round.label_useful = _to_int(ratings.get('label_useful'))
                existing_round.label_influenced = _to_int(ratings.get('label_influenced'))
                existing_round.label_attention = _to_int(ratings.get('label_attention'))
                existing_round.label_more = _to_int(ratings.get('label_more'))
            for k in ['theme_selection', 'article', 'mid_questionnaire']:
                if k in data:
                    val = getattr(existing_round, k)
                    if val and isinstance(val, dict) and isinstance(data[k], dict):
                        val.update(data[k])
                        setattr(existing_round, k, val)
                    else:
                        setattr(existing_round, k, data[k])
            existing_round.timestamp = datetime.utcnow()

        db.session.commit()
        print(f"[SAVE] '{section}' saved for participant {pid} at {datetime.utcnow().isoformat()}")

    except Exception as e:
        db.session.rollback()
        print(f"[ERROR] Failed to save '{section}' for participant {pid}: {e}")



@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/demographics', methods=['GET', 'POST'])
def demographics():
    if request.method == 'POST':
        gender = request.form.get('gender')
        gender_self = request.form.get('gender_self_describe', '').strip()
        age_group = request.form.get('age_group')
        country = request.form.get('country')
        other_country = request.form.get('other_country', '').strip()
        education = request.form.get('education')
        other_education = request.form.get('other_education', '').strip()

        gender_final = gender_self if gender == 'Self-describe' else gender
        country_final = other_country if country == 'Other' else country
        education_final = other_education if education == 'Other' else education
        # Political leaning question (new)
        political_leaning = request.form.get('political_leaning')
        political_leaning_other = request.form.get('political_leaning_other', '').strip()
        political_final = political_leaning_other if political_leaning == 'Other' else political_leaning

        if age_group == '15 or younger':
            return render_template('thank_you.html', message="Sorry, you do not meet the age criteria for this study.")

        update_participant_data('demographics', {
            'gender': gender_final,
            'age_group': age_group,
            'country': country_final,
            'education': education_final,
            'political_leaning': political_final
        })

        session['demographics_completed'] = True
        session['round'] = 1
        return redirect(url_for('pre_questionnaire'))

    return render_template('demographics.html')

@app.route('/pre-questionnaire', methods=['GET', 'POST'])
@require_previous_step('demographics')
def pre_questionnaire():
    if request.method == 'POST':
        # Devices: Get list of all checked devices, including "Other"
        devices = request.form.getlist('device')
        device_other = request.form.get('device_other', '').strip()
        if 'Other' in devices and device_other:
            devices = [d if d != 'Other' else f"Other: {device_other}" for d in devices]

        # Platform: Get value and check if "Other" was selected
        platform = request.form.get('platform')
        platform_other = request.form.get('platform_other', '').strip()
        if platform == 'Other' and platform_other:
            platform = f"Other: {platform_other}"

        data = {
            'news_frequency': request.form.get('news_frequency'),
            # 'devices': devices,
            'platform': platform,
            'favourite_topic_1': request.form.get('favourite_topic_1'),
            'least_favourite_topic_1': request.form.get('least_favourite_topic_1'),
            'favourite_topic_2': request.form.get('favourite_topic_2'),
            'least_favourite_topic_2': request.form.get('least_favourite_topic_2'),
            'enjoy_topic_1': request.form.get('enjoy_topic_1'),
            'enjoy_topic_2': request.form.get('enjoy_topic_2'),
            'avoid_topic_1': request.form.get('avoid_topic_1'),
            'avoid_topic_2': request.form.get('avoid_topic_2'),
            'attention_check': request.form.get('attention_check'),
            'avoid_news': request.form.get('avoid_news'),
            'avoid_reasons': request.form.getlist('avoid_reasons'),
            'avoid_other': request.form.get('avoid_other'),
            # 'reason_rank_1': request.form.get('reason_rank_1'),
            # 'reason_rank_2': request.form.get('reason_rank_2'),
            # 'trust_level': request.form.get('trust_level'),
        }

        # Process avoid_reasons to replace 'other' with the specified text
        if 'other' in data['avoid_reasons'] and data['avoid_other']:
            data['avoid_reasons'] = [r if r != 'other' else f"other: {data['avoid_other']}" for r in data['avoid_reasons']]

        update_participant_data('pre_questionnaire', data)
        session['pre_questionnaire_data'] = data
        session['pre_questionnaire_completed'] = True

        # Persist which topic list (A/B) round 1 starts with.
        _ensure_topic_start_list()

        # Pick the first article from the participant's favourite topic of that list.
        round_number = 1
        list_name = _list_for_round(round_number)
        fav_selection = data.get('favourite_topic_1') if list_name == 'A' else data.get('favourite_topic_2')
        fav_topic = _map_list_topic(list_name, fav_selection)

        if fav_topic:
            candidates = df[df[TOPIC_COL].astype(str).str.strip().str.lower() == fav_topic.strip().lower()]
        else:
            candidates = df

        first_row = candidates.sample(1).iloc[0] if not candidates.empty else df.sample(1).iloc[0]
        first_article_id = int(first_row['index'])

        session['first_article_id'] = first_article_id
        session['round'] = 1
        session['seen_article_ids'] = [first_article_id]
        return redirect(url_for('instructions'))
    
    return render_template('pre_questionnaire.html')


@app.route('/instructions', methods=['GET', 'POST'])
@require_previous_step('pre_questionnaire')
def instructions():
    if request.method == 'POST':
        session['instructions_completed'] = True
        return redirect(url_for('article', article_id=session['first_article_id']))
    return render_template('instructions.html')


from flask import render_template, request, redirect, url_for, session
from datetime import datetime, timedelta
import random

@app.route('/article/<int:article_id>', methods=['GET', 'POST'])
@require_previous_step('instructions')
def article(article_id):
    # if article_id not in df['index'].values:
    #     return redirect(url_for('select_article'))

    row = df[df['index'] == article_id]
    if row.empty:
        # If an invalid/unknown article_id is requested, fall back to a random known article.
        fallback_row = df.sample(1).iloc[0]
        return redirect(url_for('article', article_id=int(fallback_row['index'])))

    article_data = row.iloc[0].to_dict()
    # Normalize keys to what templates expect (Title, Content, Image URL, Author, Date)
    article_data = normalize_article_row(article_data)
    article_index = article_data['index']
    main_article_stable_id = get_stable_article_id(article_data)
    round_number = session.get('round', 1)

    # Enable debug panel via query param: /article/<id>?debug=1
    debug_flag = str(request.args.get('debug', '')).strip().lower() in ('1', 'true', 'yes', 'on')

    # Determine which topic list (A/B) applies to this round and the participant's
    # favourite/least favourite topics for that list.
    _ensure_topic_start_list()
    list_name = _list_for_round(int(round_number))
    pq = session.get('pre_questionnaire_data') or {}
    if not isinstance(pq, dict):
        pq = {}

    fav_selection = pq.get('favourite_topic_1') if list_name == 'A' else pq.get('favourite_topic_2')
    least_selection = pq.get('least_favourite_topic_1') if list_name == 'A' else pq.get('least_favourite_topic_2')
    fav_topic = _map_list_topic(list_name, fav_selection)
    least_topic = _map_list_topic(list_name, least_selection)

    # Track seen articles
    seen_ids = set(session.get('seen_article_ids', []))
    seen_ids.add(article_index)
    session['seen_article_ids'] = list(seen_ids)

    # # Determine if label should be shown for this article
    # if round_number == 1:
    #     theme_articles = session.get('theme_articles', [])
    #     selected_article = next((a for a in theme_articles if a['index'] == article_index), {})
    #     show_label = selected_article.get('show_label', False)
    # else:
    #     recommendations_meta = session.get('recommendations_meta', {})
    #     show_label = recommendations_meta.get(str(article_index), False)

    # session['last_article_had_label'] = show_label

    # Generate recommendations (only on GET)
    if request.method == 'GET':
        # Ensure main article matches the favourite topic for this round's list.
        # If not, pick a fresh main article from the correct topic.
        if fav_topic:
            current_topic_str = _normalize_topic_value(article_data.get(TOPIC_COL, ''))
            fav_topic_str = _normalize_topic_value(fav_topic)
            if current_topic_str != fav_topic_str:
                main_candidates = df[
                    (df[TOPIC_COL].astype(str).str.strip().str.lower() == fav_topic_str) &
                    (~df['index'].isin(seen_ids))
                ]
                if main_candidates.empty:
                    main_candidates = df[df[TOPIC_COL].astype(str).str.strip().str.lower() == fav_topic_str]
                if not main_candidates.empty:
                    new_row = main_candidates.sample(1).iloc[0]
                    return redirect(url_for('article', article_id=int(new_row['index'])))

        # Build exactly two recommendations:
        # - one from favourite topic
        # - one from least favourite topic
        # in random order.
        try:
            rec_records = []

            def _topic_mask(topic_value: str | None):
                if not topic_value:
                    return None
                topic_str = _normalize_topic_value(topic_value)
                return df[TOPIC_COL].astype(str).str.strip().str.lower() == topic_str

            def _pick_one_from_topic(topic_value: str | None):
                if not topic_value:
                    return None
                mask = _topic_mask(topic_value)
                if mask is None:
                    return None

                # Prefer unseen and not-the-main-article.
                candidates = df[mask & (~df['index'].isin(seen_ids)) & (df['index'] != article_index)]
                if not candidates.empty:
                    return candidates.sample(1).iloc[0].to_dict()

                # Next allow seen, but still avoid main article.
                candidates = df[mask & (df['index'] != article_index)]
                if not candidates.empty:
                    return candidates.sample(1).iloc[0].to_dict()

                # Finally, allow even the main article (duplicate main+rec is acceptable).
                candidates = df[mask]
                if not candidates.empty:
                    return candidates.sample(1).iloc[0].to_dict()

                return None

            rec_fav = _pick_one_from_topic(fav_topic)
            rec_least = _pick_one_from_topic(least_topic)

            # Fallback policy (per study requirement): never sample random topics.
            # If least-topic (or fav-topic) candidates are missing, duplicate within allowed topics.
            if rec_fav is None and fav_topic:
                rec_fav = _pick_one_from_topic(fav_topic)

            if rec_least is None:
                # Prefer duplicating the favourite-topic recommendation.
                if fav_topic:
                    rec_least = _pick_one_from_topic(fav_topic)
                # If we still have nothing, try least_topic again (may be None).
                if rec_least is None and least_topic:
                    rec_least = _pick_one_from_topic(least_topic)

            if rec_fav is not None:
                rec_records.append(rec_fav)
            if rec_least is not None:
                rec_records.append(rec_least)

            # Ensure we have two recommendations when possible (duplicates allowed).
            if len(rec_records) == 1:
                # Duplicate the one we have.
                rec_records.append(rec_records[0])
            elif len(rec_records) == 0:
                # Absolute last resort: duplicate the current article.
                rec_records = [article_data, article_data]

            random.shuffle(rec_records)

            # Normalize each recommendation for template compatibility
            recommendations = [normalize_article_row(rec) for rec in rec_records[:2]]
        except Exception as e:
            app.logger.exception('Failed to build recommendations: %s', e)
            recommendations = []

        recommendations_meta = {}
        # Removed condition-based labeling

        session['current_recommendations'] = [rec['index'] for rec in recommendations]
        session['recommendations_meta'] = recommendations_meta
    else:
        # On POST restore previous recommendations from session
        recommendations = []
        ids = session.get('current_recommendations', [])
        rec_meta = session.get('recommendations_meta', {})
        for rec_id in ids:
            row = df[df['index'] == rec_id]
            if not row.empty:
                rec_data = row.iloc[0].to_dict()
                rec_data = normalize_article_row(rec_data)
                # rec_data['show_label'] = rec_meta.get(str(rec_id), False)
                recommendations.append(rec_data)

    # # Generate random C2PA badge if needed
    # cr_labels = ['cr1.png', 'cr2.png', 'cr3.png', 'cr4.png']
    # cr_label = random.choice(cr_labels) if condition == 'c2pa' else None

    # Handle POST (ratings finished / continue)
    if request.method == 'POST':
        # We no longer let users click-select a recommended article.
        # The current main article is the unit of a round.
        selected_article_id = None
        selected_article_title = ""

        # Collect ratings
        recommendations_ids = session.get('current_recommendations', [])

        recommendation_stable_ids = []
        recommendation_titles = []
        for rec_id in recommendations_ids:
            rec_row = df[df['index'] == rec_id]
            if rec_row.empty:
                recommendation_stable_ids.append(None)
                recommendation_titles.append(None)
                continue
            rec_record = normalize_article_row(rec_row.iloc[0].to_dict())
            recommendation_stable_ids.append(get_stable_article_id(rec_record))
            recommendation_titles.append(rec_record.get('Title', None))

        # Collect ratings
        # IMPORTANT: the actual form fields are hidden inputs named like
        # `likelihood_<rec_id>` and `label_more` (no `_hidden` suffix).
        # The `_hidden` inputs are created dynamically in the rating wizard HTML,
        # but they are not part of the <form> element and therefore are not submitted.
        ratings = {}

        def _pick_rating_value(*field_names: str) -> str:
            for name in field_names:
                if not name:
                    continue
                v = request.form.get(name)
                if v is not None:
                    return v
            return ''

        for i, rec_id in enumerate(recommendations_ids):
            # Prefer the stable naming scheme used by the hidden inputs in the form:
            # e.g. likelihood_891, constructive_891, ...
            ratings[f'likelihood_{rec_id}'] = _pick_rating_value(
                f'likelihood_{rec_id}',
                f'likelihood_{i}',
                f'likelihood_{rec_id}_hidden',
                f'likelihood_{i}_hidden',
            )
            for stmt in ['constructive', 'understandable', 'trustworthy', 'relevant']:
                ratings[f'{stmt}_{rec_id}'] = _pick_rating_value(
                    f'{stmt}_{rec_id}',
                    f'{stmt}_{i}',
                    f'{stmt}_{rec_id}_hidden',
                    f'{stmt}_{i}_hidden',
                )

        for stmt in ['label_understandable', 'label_useful', 'label_influenced', 'label_attention', 'label_more']:
            ratings[stmt] = _pick_rating_value(stmt, f'{stmt}_hidden')

        # update_participant_data('round', {
        #     'round': round_number,
        #     'selected_article_id': selected_article_id,
        #     'selected_article_title': df[df['index'] == selected_article_id].iloc[0]['Title'],
        #     'selected_article_had_label': selected_article_had_label,
        #     'label_explained': label_explained
        # })
        update_participant_data('round', {
            'round': round_number,
            'article_id': article_index,
            'article_stable_id': main_article_stable_id,
            'article': {
                'main_article_id': article_index,
                'main_article_stable_id': main_article_stable_id,
                'main_article_title': article_data.get('Title', ''),
                'recommendations': session.get('current_recommendations', []),
                'recommendations_stable_ids': recommendation_stable_ids,
                'recommendations_titles': recommendation_titles,
                'ratings': ratings
            }
        })

        # Advance to next round/article (6 rounds total)
        total_rounds = 6
        if round_number < total_rounds:
            session['round'] = round_number + 1
            # pick a new main article not seen yet
            remaining = df[~df['index'].isin(seen_ids)]
            if remaining.empty:
                # if we run out, allow repeats (shouldn't happen normally)
                next_row = df.sample(1).iloc[0]
            else:
                next_row = remaining.sample(1).iloc[0]
            next_id = int(next_row['index'])
            session['next_article'] = next_id
            seen_ids.add(next_id)
            session['seen_article_ids'] = list(seen_ids)
            return redirect(url_for('article', article_id=next_id))

        # After final round, finish the study (post-questionnaire not used in this prototype)
        session['article_completed'] = True
        session['mid_questionnaire_completed'] = True
        session['post_questionnaire_completed'] = True
        return redirect(url_for('thank_you'))

    # Add random metadata if missing
    if 'Author' not in article_data or not article_data['Author']:
        article_data['Author'] = random.choice([
            "Olivia Hansen", "Jonas Berg", "Elena Novak", "Anders Dahl", 
            "Nora Larsen", "Mateo Sæther", "Sofie Zhang", "Henrik Müller"
        ])

    if 'Date' not in article_data or not article_data['Date']:
        days_ago = random.randint(0, 5)
        article_data['Date'] = (datetime.now() - timedelta(days=days_ago)).strftime("%B %d, %Y")

    return render_template(
        'article.html',
        article=article_data,
        recommendations=recommendations,
        round_number=round_number,
        total_rounds=6,
        debug=debug_flag,
        topic_col=TOPIC_COL,
        topic_start_list=session.get('topic_start_list'),
        topic_list=list_name,
        fav_topic=fav_topic,
        least_topic=least_topic,
    )



@app.route('/mid-questionnaire', methods=['GET', 'POST'])
@require_previous_step('article')
def mid_questionnaire():
    article_id = session.get('next_article')
    article = df[df['index'] == article_id].iloc[0].to_dict()
    article = normalize_article_row(article)

    condition = session.get('condition')
    # show_label = session.get('last_article_had_label', False)

    if request.method == 'POST':
        selected_elements = request.form.getlist('choice_elements')
        other_text = request.form.get('choice_elements_other', '').strip()
        trust_article = request.form.get('trust_article')
        trust_image = request.form.get('trust_image')

        # if not selected_elements or ("Other (please specify)" in selected_elements and not other_text):
        #     return render_template('mid_questionnaire.html',
        #                            article=article,
        #                            condition=condition,
        #                            show_label=show_label,
        #                            error="Please complete the form.")
        # if "Don't know / None of these" in selected_elements and len(selected_elements) > 1:
        #     return render_template('mid_questionnaire.html',
        #                            article=article,
        #                            condition=condition,
        #                            show_label=show_label,
        #                            error="'Don't know' cannot be combined.")
        # if selected_elements == ['Other (please specify)']:
        #     selected_elements = [f"Other: {other_text}"]

        selected_elements_out = []
        for el in selected_elements:
            if el == "Other":
                if other_text:
                    selected_elements_out.append(f"Other: {other_text}")
                else:
                    return render_template('mid_questionnaire.html',
                                        article=article,
                                        condition=condition,
                                        # show_label=show_label,
                                        error="Please specify what 'Other' means.")
            else:
                selected_elements_out.append(el)

        if "Don't know/None of these" in selected_elements and len(selected_elements) > 1:
            return render_template('mid_questionnaire.html',
                                article=article,
                                condition=condition,
                                # show_label=show_label,
                                error="'Don't know' cannot be combined.")

        update_participant_data('round', {
            'round': session.get('round', 1),
            'article_id': article_id,
            # 'selected_article_had_label': show_label,
            'mid_questionnaire': {
                'selected_elements': selected_elements_out,
                'trust_article': trust_article,
                'trust_image': trust_image
            }
        })

        session['mid_questionnaire_completed'] = True
        if session.get('round', 1) < 6:
            session['round'] += 1
            return redirect(url_for('article', article_id=session.get('next_article')))
        return redirect(url_for('post_questionnaire'))

    return render_template(
        'mid_questionnaire.html',
        article=article,
        condition=condition,
        # show_label=show_label,
        debug=False
    )




# @app.route('/post-questionnaire', methods=['GET', 'POST'])
# @require_previous_step('mid_questionnaire')
# def post_questionnaire():
#     condition = session.get('condition')

#     if request.method == 'POST':
#         confidence = request.form.get('confidence')
#         feedback = request.form.get('feedback')
#         score_meaning = request.form.getlist('score_meaning')
#         score_meaning_other = request.form.get('score_meaning_other')
#         label_expectation = request.form.getlist('label_expectation')
#         label_expectation_other = request.form.get('label_expectation_other')
#         if condition in ['color', 'no_color']:
#             grade_basis = request.form.get('grade_basis')
#             grade_basis_other = request.form.get('grade_basis_other')
#         else:
#             grade_basis = None
#             grade_basis_other = None
#         familiar_trust_levels = request.form.get('familiar_trust_levels')
#         familiar_nutriscore = request.form.get('familiar_nutriscore')

#         likert_items = ['understood_label', 'visual_design', 'decision_support', 'info_usefulness',
#                         'image_trust', 'evaluate_trustworthiness', 'more_labels', 'attention_check']
#         likert_responses = {}
#         for item in likert_items:
#             val = request.form.get(item)
#             if not val:
#                 return render_template('post_questionnaire.html', error="Please answer all questions.")
#             likert_responses[item] = int(val)

#         update_participant_data('post_questionnaire', {
#             'confidence': confidence,
#             'feedback': feedback,
#             'score_meaning': [
#                 f"Other: {score_meaning_other}" if val == "Other" and score_meaning_other else val
#                 for val in score_meaning
#             ],
#             'label_expectation': [
#                 f"Other: {label_expectation_other}" if val == "Other" and label_expectation_other else val
#                 for val in label_expectation
#             ],
#             'familiar_trust_levels': familiar_trust_levels,
#             'familiar_nutriscore': familiar_nutriscore,
#             'grade_basis': f"Other: {grade_basis_other}" if grade_basis == "Other" and grade_basis_other else grade_basis,
#             'likert_responses': likert_responses,
#             'label_present': session.get('last_article_had_label', False)
#         })
#         session['post_questionnaire_completed'] = True
#         return redirect(url_for('thank_you'))

#     return render_template(
#         'post_questionnaire.html',
#         condition=session.get('condition'))

@app.route('/post-questionnaire', methods=['GET', 'POST'])
@require_previous_step('mid_questionnaire')
def post_questionnaire():
    condition = session.get('condition')

    if request.method == 'POST':
        confidence = request.form.get('confidence')
        feedback = request.form.get('feedback')
        familiar_trust_levels = request.form.get('familiar_trust_levels')
        familiar_nutriscore = request.form.get('familiar_nutriscore')

        # Only handle these if the fields are present (i.e., if condition is NOT 'nolabel')
        if condition in ['color', 'no_color', 'c2pa']:
            score_meaning = request.form.getlist('score_meaning')
            score_meaning_other = request.form.get('score_meaning_other')
            label_expectation = request.form.getlist('label_expectation')
            label_expectation_other = request.form.get('label_expectation_other')

            if condition in ['color', 'no_color']:
                grade_basis = request.form.get('grade_basis')
                grade_basis_other = request.form.get('grade_basis_other')
            else:
                grade_basis = None
                grade_basis_other = None

            # Process Likert
            likert_items = ['understood_label', 'visual_design', 'decision_support', 'info_usefulness',
                            'image_trust', 'evaluate_trustworthiness', 'more_labels', 'attention_check']
            likert_responses = {}
            for item in likert_items:
                val = request.form.get(item)
                if not val:
                    return render_template('post_questionnaire.html', error="Please answer all questions.", condition=condition)
                likert_responses[item] = int(val)

            # Save all data
            update_participant_data('post_questionnaire', {
                'confidence': confidence,
                'feedback': feedback,
                'score_meaning': [
                    f"Other: {score_meaning_other}" if val == "Other" and score_meaning_other else val
                    for val in score_meaning
                ],
                'label_expectation': [
                    f"Other: {label_expectation_other}" if val == "Other" and label_expectation_other else val
                    for val in label_expectation
                ],
                'familiar_trust_levels': familiar_trust_levels,
                'familiar_nutriscore': familiar_nutriscore,
                'grade_basis': f"Other: {grade_basis_other}" if grade_basis == "Other" and grade_basis_other else grade_basis,
                'likert_responses': likert_responses,
                'label_present': session.get('last_article_had_label', False)
            })
        else:  # NO LABEL condition
            # Just save the available data
            update_participant_data('post_questionnaire', {
                'confidence': confidence,
                'feedback': feedback,
                'familiar_trust_levels': familiar_trust_levels,
                'familiar_nutriscore': familiar_nutriscore,
                'label_present': session.get('last_article_had_label', False)
            })
        session['post_questionnaire_completed'] = True
        return redirect(url_for('thank_you'))

    return render_template(
        'post_questionnaire.html',
        condition=session.get('condition'))

@app.route('/thank-you')
@require_previous_step('post_questionnaire')
def thank_you():
    condition = session.get('condition', 'none')
    return render_template('thank_you.html', condition=condition)




@app.route('/reset-db')
def reset_db():
    try:
        Round.query.delete()
        Participant.query.delete()
        db.session.commit()
        return "База данных очищена."
    except Exception as e:
        db.session.rollback()
        return f"Ошибка при очистке: {e}"



if __name__ == '__main__':
    app.run(debug=True, port=5001)
