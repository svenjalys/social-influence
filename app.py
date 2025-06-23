from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy #for sqlite
import pandas as pd
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
###


RESPONSES_DIR = "responses"
os.makedirs(RESPONSES_DIR, exist_ok=True)

@app.before_request
def capture_prolific_id():
    pid = request.args.get('PROLIFIC_PID')
    if pid:
        session['prolific_id'] = pid

@app.before_request
def assign_condition():
    # 1. Capture Prolific PID from URL
    pid = request.args.get('PROLIFIC_PID')
    if pid:
        session['prolific_id'] = pid

    # 2. Assign condition if not already in session
    if 'condition' not in session:
        from sqlalchemy import func

        # Count number of participants per condition
        condition_counts = dict(
            db.session.query(Participant.condition, func.count(Participant.id))
            .group_by(Participant.condition)
            .all()
        )

        # Ensure all conditions are represented
        all_conditions = ['color', 'no_color', 'c2pa', 'nolabel']
        for cond in all_conditions:
            condition_counts.setdefault(cond, 0)

        # Pick condition with the lowest count
        session['condition'] = min(condition_counts, key=condition_counts.get)

    # 3. Force redirect to landing if no PID and not on public route
    allowed_routes = {'landing', 'static'}
    if not session.get('prolific_id') and request.endpoint not in allowed_routes:
        return redirect(url_for('landing'))


@app.before_request
def require_participant():
    allowed_routes = {'landing', 'static'}
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

df = pd.read_csv("articles.csv")
df.reset_index(inplace=True)

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
                condition=session.get('condition', 'unknown'),
                timestamp_start=datetime.utcnow()
            )
            db.session.add(participant)
            db.session.flush()  # Assigns participant.id without full commit

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

        if age_group == '15 or younger':
            return render_template('thank_you.html', message="Sorry, you do not meet the age criteria for this study.")

        update_participant_data('demographics', {
            'gender': gender_final,
            'age_group': age_group,
            'country': country_final,
            'education': education_final
        })

        session['demographics_completed'] = True
        session['round'] = 1
        return redirect(url_for('pre_questionnaire'))

    return render_template('demographics.html')

@app.route('/pre-questionnaire', methods=['GET', 'POST'])
@require_previous_step('demographics')
def pre_questionnaire():
    # if request.method == 'POST':
    #     data = {
    #         'news_frequency': request.form.get('news_frequency'),
    #         'device': request.form.get('device'),
    #         'device_other': request.form.get('device_other') if request.form.get('device') == 'Other' else None,
    #         'platform': request.form.get('platform'),
    #         'platform_other': request.form.get('platform_other') if request.form.get('platform') == 'Other' else None,
    #         'news_sources': request.form.get('news_sources'),
    #         'attention_check': request.form.get('attention_check'),
    #         'trust_level': request.form.get('trust_level')
    #     }
    #     update_participant_data('pre_questionnaire', data)
    #     session['pre_questionnaire_completed'] = True
    #     session['round'] = 1
    #     return redirect(url_for('select_article'))
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

        # News sources: Get all checked, including "Other"
        sources = request.form.getlist('news_sources')
        sources_other_checked = 'Other' in request.form.getlist('sources_other')  # checkbox for Other
        sources_other_text = request.form.get('sources_other_text', '').strip()
        if sources_other_checked and sources_other_text:
            sources.append(f"Other: {sources_other_text}")

        data = {
            'news_frequency': request.form.get('news_frequency'),
            'devices': devices,                      # Now a list with "Other" replaced if present
            'platform': platform,                    # "Other: text" if "Other" was selected
            'news_sources': sources,                 # List, with "Other: text" if "Other" checked
            'attention_check': request.form.get('attention_check'),
            'trust_level': request.form.get('trust_level')
        }

        update_participant_data('pre_questionnaire', data)
        session['pre_questionnaire_completed'] = True
        return redirect(url_for('select_article'))
    return render_template('pre_questionnaire.html')

@app.route('/select-article', methods=['GET', 'POST'])
@require_previous_step('pre_questionnaire')
def select_article():
    if request.method == 'POST':
        selected_article_id = int(request.form['selected_article_id'])
        session['next_article'] = selected_article_id

        theme_articles = session.get('theme_articles', [])
        selected_article = next((a for a in theme_articles if a['index'] == selected_article_id), {})
        session['last_article_had_label'] = selected_article.get('show_label', False)

        article_row = df[df['index'] == selected_article_id]
        if not article_row.empty:
            article = article_row.iloc[0]
            # selected_article_title = article_row.iloc[0]['Title']
            # update_participant_data('theme_selection', {
            #     'selected_article_id': selected_article_id,
            #     'selected_article_title': article['Title'],
            #     'selected_article_category': article['Category'],
            #     'condition': session.get('condition', 'unknown')
            # })
            update_participant_data('round', {
                'theme_selection': {
                    'selected_article_id': selected_article_id,
                    'selected_article_title': article['Title'],
                    'selected_article_category': article['Category'],
                    'condition': session.get('condition', 'unknown')
                }
            })
        # else:
        #     selected_article_title = ""

        session['select_article_completed'] = True
        session['seen_article_ids'] = [selected_article_id]  # Init seen
        return redirect(url_for('article', article_id=selected_article_id))

    # Select 4 articles from different categories
    grouped = df.groupby(df['Category'].str.title())
    selected_categories = random.sample(list(grouped.groups), k=min(4, len(grouped)))
    selected_articles = [grouped.get_group(cat).sample(1).iloc[0] for cat in selected_categories]

    condition = session.get('condition')
    theme_articles = []
    for a in selected_articles:
        article_dict = a.to_dict()
        article_dict['index'] = int(a['index'])
        article_dict['show_label'] = condition != 'nolabel'
        theme_articles.append(article_dict)

    session['theme_articles'] = theme_articles

    return render_template(
        'select_article.html',
        articles=theme_articles,
        condition=condition
    )


from flask import render_template, request, redirect, url_for, session
from datetime import datetime, timedelta
import random

@app.route('/article/<int:article_id>', methods=['GET', 'POST'])
@require_previous_step('select_article')
def article(article_id):
    if article_id not in df['index'].values:
        return redirect(url_for('select_article'))

    article_data = df[df['index'] == article_id].iloc[0].to_dict()
    article_index = article_data['index']
    condition = session.get('condition')
    round_number = session.get('round', 1)

    # Track seen articles
    seen_ids = set(session.get('seen_article_ids', []))
    seen_ids.add(article_index)
    session['seen_article_ids'] = list(seen_ids)

    # Determine if label should be shown for this article
    if round_number == 1:
        theme_articles = session.get('theme_articles', [])
        selected_article = next((a for a in theme_articles if a['index'] == article_index), {})
        show_label = selected_article.get('show_label', False)
    else:
        recommendations_meta = session.get('recommendations_meta', {})
        show_label = recommendations_meta.get(str(article_index), False)

    session['last_article_had_label'] = show_label

    # Generate recommendations (only on GET)
    if request.method == 'GET':
        recommendations_df = df[
            (df['Category'] == article_data['Category']) &
            (~df['index'].isin(seen_ids))
        ]
        recommendations = recommendations_df.sample(n=min(4, len(recommendations_df))).to_dict(orient='records')

        recommendations_meta = {}
        if condition in ['color', 'no_color', 'c2pa']:
            labeled_indices = random.sample(range(len(recommendations)), min(2, len(recommendations)))
            for i, rec in enumerate(recommendations):
                show = i in labeled_indices
                rec['show_label'] = show
                recommendations_meta[str(rec['index'])] = show
        else:
            for rec in recommendations:
                rec['show_label'] = False
                recommendations_meta[str(rec['index'])] = False

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
                rec_data['index'] = rec_id
                rec_data['show_label'] = rec_meta.get(str(rec_id), False)
                recommendations.append(rec_data)

    # Generate random C2PA badge if needed
    cr_labels = ['cr1.png', 'cr2.png', 'cr3.png', 'cr4.png']
    cr_label = random.choice(cr_labels) if condition == 'c2pa' else None

    # Handle POST (article selection)
    if request.method == 'POST':
        selected_article_id = int(request.form['selected_article_id'])
        # selected_article_title = request.form.get('selected_article_title')
        selected_article_had_label = request.form.get('selected_article_had_label') == 'true'
        label_explained = request.form.get('label_explained') == 'true'

        # Save label state for selected article
        recommendations_meta = session.get('recommendations_meta', {})
        session['selected_from_meta'] = recommendations_meta.get(str(selected_article_id), False)

        session['next_article'] = selected_article_id
        session['last_article_had_label'] = selected_article_had_label
        seen_ids.add(selected_article_id)
        session['seen_article_ids'] = list(seen_ids)

        # NEW: Get the article title from the DataFrame
        article_row = df[df['index'] == selected_article_id]
        if not article_row.empty:
            selected_article_title = article_row.iloc[0]['Title']
        else:
            selected_article_title = ""

        # update_participant_data('round', {
        #     'round': round_number,
        #     'selected_article_id': selected_article_id,
        #     'selected_article_title': df[df['index'] == selected_article_id].iloc[0]['Title'],
        #     'selected_article_had_label': selected_article_had_label,
        #     'label_explained': label_explained
        # })
        update_participant_data('round', {
            'article': {
                'selected_article_id': selected_article_id,
                'selected_article_title': selected_article_title,
                'selected_article_had_label': selected_article_had_label,
                'label_explained': label_explained
            }
        })

        session['article_completed'] = True
        return redirect(url_for('mid_questionnaire'))

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
        condition=condition,
        cr_label=cr_label,
        show_label=show_label,
        round_number=round_number,
        debug=False
    )



@app.route('/mid-questionnaire', methods=['GET', 'POST'])
@require_previous_step('article')
def mid_questionnaire():
    article_id = session.get('next_article')
    article = df[df['index'] == article_id].iloc[0].to_dict()
    article['index'] = article_id

    condition = session.get('condition')
    show_label = session.get('last_article_had_label', False)

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
                                        show_label=show_label,
                                        error="Please specify what 'Other' means.")
            else:
                selected_elements_out.append(el)

        if "Don't know/None of these" in selected_elements and len(selected_elements) > 1:
            return render_template('mid_questionnaire.html',
                                article=article,
                                condition=condition,
                                show_label=show_label,
                                error="'Don't know' cannot be combined.")

        update_participant_data('round', {
            'round': session.get('round', 1),
            'article_id': article_id,
            'selected_article_had_label': show_label,
            'mid_questionnaire': {
                'selected_elements': selected_elements_out,
                'trust_article': trust_article,
                'trust_image': trust_image
            }
        })

        session['mid_questionnaire_completed'] = True
        if session.get('round', 1) < 3:
            session['round'] += 1
            return redirect(url_for('article', article_id=session.get('next_article')))
        else:
            return redirect(url_for('post_questionnaire'))

    return render_template(
        'mid_questionnaire.html',
        article=article,
        condition=condition,
        show_label=show_label,
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

if __name__ == '__main__':
    app.run(debug=True)
