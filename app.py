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

# Hent Prolific PID fra URL ved hver forespørsel
@app.before_request
def capture_prolific_id():
    pid = request.args.get('PROLIFIC_PID')
    if pid:
        session['prolific_id'] = pid

# Tildel condition basert på balanse
@app.before_request
def assign_condition():
    if 'condition' not in session:
        condition_counts = {'color': 0, 'no_color': 0, 'c2pa': 0, 'nolabel':0}
        for filename in os.listdir(RESPONSES_DIR):
            if filename.endswith('.json'):
                with open(os.path.join(RESPONSES_DIR, filename), 'r') as f:
                    try:
                        data = json.load(f)
                        cond = data.get('condition')
                        if cond in condition_counts:
                            condition_counts[cond] += 1
                    except Exception:
                        continue
        session['condition'] = min(condition_counts, key=condition_counts.get)
        # session.pop('condition', None)
        # session['condition'] = 'color'  # or 'no_color' or 'c2pa'


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

    # Try to get existing participant, else create new one
    participant = Participant.query.filter_by(prolific_id=pid).first()
    if not participant:
        participant = Participant(
            prolific_id=pid,
            condition=session.get('condition', 'unknown'),
            timestamp_start=datetime.utcnow()
        )
        db.session.add(participant)
        db.session.commit()  # commit so participant.id is assigned

    # Save data based on section
    if section == 'demographics':
        participant.demographics = data
    elif section == 'pre_questionnaire':
        participant.pre_questionnaire = data
    elif section == 'post_questionnaire':
        participant.post_questionnaire = data
    elif section == 'round':
        round_number = session.get('round', 1)
        # Find existing round for this participant & number
        existing_round = Round.query.filter_by(participant_id=participant.id, round_number=round_number).first()
        if existing_round:
            # Update existing round (merge data)
            if data.get('theme_selection'):
                existing_round.theme_selection = data['theme_selection']
            if data.get('article'):
                existing_round.article = data['article']
            if data.get('mid_questionnaire'):
                existing_round.mid_questionnaire = data['mid_questionnaire']
            existing_round.timestamp = datetime.utcnow()
        else:
            # Insert new round
            new_round = Round(
                round_number=round_number,
                participant_id=participant.id,
                theme_selection=data.get('theme_selection'),
                article=data.get('article'),
                mid_questionnaire=data.get('mid_questionnaire'),
                timestamp=datetime.utcnow()
            )
            db.session.add(new_round)

    db.session.commit()
    print(f"Saved '{section}' for participant {pid}")


# def update_participant_data(section, data):
#     pid = get_participant_id()
#     print("Prolific ID:", pid)

#     if not pid:
#         print("Ingen PID – avbryter lagring")
#         return

#     filepath = os.path.join(RESPONSES_DIR, f"{pid}.json")
#     print("Skal lagres til:", filepath)

#     if os.path.exists(filepath):
#         with open(filepath, 'r') as f:
#             pdata = json.load(f)
#     else:
#         pdata = {
#             'prolific_id': pid,
#             'condition': session.get('condition', 'unknown'),
#             'timestamp_start': datetime.utcnow().isoformat()
#         }

#     if section == 'round':
#         pdata.setdefault('rounds', []).append(data)
#     else:
#         pdata[section] = data


#     # if section == 'round':
#     #     rounds = pdata.setdefault('rounds', [])
#     #     current_round = session.get('round', 1)

#     #     # Check if there's already a round entry
#     #     for r in rounds:
#     #         if r.get('round') == current_round:
#     #             r.update(data)  # Merge into existing round
#     #             break
#     #         else:
#     #             rounds.append(data)  # Add new round if not present
#     #     else:
#     #         pdata[section] = data



#     with open(filepath, 'w') as f:
#         json.dump(pdata, f, indent=2)
#     print("Lagring fullført.")



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
        occupation = request.form.get('occupation')
        other_occupation = request.form.get('other_occupation', '').strip()

        gender_final = gender_self if gender == 'Self-describe' else gender
        country_final = other_country if country == 'Other' else country
        occupation_final = other_occupation if occupation == 'Other' else occupation

        if age_group == '15 or younger':
            return render_template('thank_you.html', message="Sorry, you do not meet the age criteria for this study.")

        update_participant_data('demographics', {
            'gender': gender_final,
            'gender_self_describe': gender_self,
            'age_group': age_group,
            'country': country_final,
            'other_country': other_country,
            'occupation': occupation_final,
            'other_occupation': other_occupation
        })
        session['demographics_completed'] = True
        session['round'] = 1
        return redirect(url_for('pre_questionnaire'))

    return render_template('demographics.html')

@app.route('/pre-questionnaire', methods=['GET', 'POST'])
@require_previous_step('demographics')
def pre_questionnaire():
    if request.method == 'POST':
        data = {
            'news_frequency': request.form.get('news_frequency'),
            'device': request.form.get('device'),
            'device_other': request.form.get('device_other') if request.form.get('device') == 'Other' else None,
            'platform': request.form.get('platform'),
            'platform_other': request.form.get('platform_other') if request.form.get('platform') == 'Other' else None,
            'news_sources': request.form.get('news_sources'),
            'attention_check': request.form.get('attention_check'),
            'trust_level': request.form.get('trust_level')
        }
        update_participant_data('pre_questionnaire', data)
        session['pre_questionnaire_completed'] = True
        session['round'] = 1
        return redirect(url_for('select_article'))
    return render_template('pre_questionnaire.html')

@app.route('/select-article', methods=['GET', 'POST'])
@require_previous_step('pre_questionnaire')
def select_article():
    if request.method == 'POST':
        selected_article_id = int(request.form['selected_article_id'])
        session['next_article'] = selected_article_id

        article_row = df[df['index'] == selected_article_id]
        if not article_row.empty:
            article = article_row.iloc[0]
            update_participant_data('theme_selection', {
                'selected_article_id': selected_article_id,
                'selected_article_title': article['Title'],
                'selected_article_category': article['Category'],
                'condition': session.get('condition', 'unknown')
            })

        session['select_article_completed'] = True
        return redirect(url_for('article', article_id=selected_article_id))

    # Group by category and randomly pick 1 article per selected category
    grouped = df.groupby(df['Category'].str.title())
    selected_categories = random.sample(list(grouped.groups), k=min(4, len(grouped)))
    selected_articles = [grouped.get_group(cat).sample(1).iloc[0] for cat in selected_categories]

    article_dicts = [a.to_dict() | {'index': int(a['index'])} for a in selected_articles]
    article_selection_indexes = [a['index'] for a in article_dicts]

    # Save selected article indexes for label logic
    session['theme_articles'] = article_dicts
    session['article_selection_indexes'] = article_selection_indexes

    return render_template(
        'select_article.html',
        articles=article_dicts,
        label_ids=article_selection_indexes,
        condition=session['condition']
    )


@app.route('/article/<int:article_id>', methods=['GET', 'POST'])
@require_previous_step('select_article')
def article(article_id):
    if article_id >= len(df):
        return redirect(url_for('select_article'))

    article_data = df.iloc[article_id].to_dict()
    article_index = article_data['index']
    condition = session.get('condition')

    # Select 4 recommendations from the same category (excluding the current article)
    recommendations_df = df[(df['Category'] == article_data['Category']) & (df['index'] != article_index)]
    recommendations = recommendations_df.sample(n=min(4, len(recommendations_df))).to_dict(orient='records')

    # Randomly assign labels to 2 recommendations
    rec_indexes = [rec['index'] for rec in recommendations]
    label_shown_ids = set(random.sample(rec_indexes, min(2, len(rec_indexes))))

    # Add article_selection_indexes to label_shown_ids if condition requires labels
    article_selection_indexes = session.get('article_selection_indexes', [])
    if condition in ['color', 'no_color', 'c2pa']:
        label_shown_ids.update(article_selection_indexes)

    # Store current label state in session
    session['label_shown_ids'] = list(label_shown_ids)

    if request.method == 'POST':
        selected_article_id = int(request.form['selected_article_id'])
        session['next_article'] = selected_article_id

        label_explained = request.form.get('label_explained') == 'true'
        selected_article_had_label = request.form.get('selected_article_had_label') == 'true'

        if selected_article_had_label:
            label_shown = set(session.get('label_shown_ids', []))
            label_shown.add(selected_article_id)
            session['label_shown_ids'] = list(label_shown)

        update_participant_data('round', {
            'round': session.get('round', 1),
            'selected_article_id': selected_article_id,
            'selected_article_title': df[df['index'] == selected_article_id].iloc[0]['Title'],
            'selected_article_had_label': selected_article_had_label,
            'label_explained': label_explained
        })

        session['article_completed'] = True
        return redirect(url_for('mid_questionnaire'))

    # Assign random CR label if needed
    cr_labels = ['cr1.png', 'cr2.png', 'cr3.png', 'cr4.png']
    cr_label = random.choice(cr_labels) if condition == 'c2pa' else None

    # Show label only if this article was in the labeled list
    show_label = article_index in session.get('label_shown_ids', [])

    return render_template(
        'article.html',
        article=article_data,
        recommendations=recommendations,
        label_shown_ids=session['label_shown_ids'],
        condition=condition,
        cr_label=cr_label,
        show_label=show_label,
        debug=True
    )




@app.route('/mid-questionnaire', methods=['GET', 'POST'])
@require_previous_step('article')
def mid_questionnaire():
    article_id = session.get('next_article')
    article = df.iloc[article_id].to_dict()
    article['index'] = article_id 

    condition = session.get('condition')
    label_shown_ids = session.get('label_shown_ids', [])

    #Debug: Print current article ID and label logic
    print(f"[DEBUG] Article ID: {article_id}")
    print(f"[DEBUG] Label condition: {condition}")
    print(f"[DEBUG] Label shown IDs: {label_shown_ids}")
    print(f"[DEBUG] Should show label: {article_id in label_shown_ids}")

    if request.method == 'POST':
        selected_elements = request.form.getlist('choice_elements')
        other_text = request.form.get('other_element')
        
        if not selected_elements:
            return render_template('mid_questionnaire.html', error="Please select at least one element that influenced your choice.",
                                   article=article, condition=condition, label_shown_ids=label_shown_ids)
        
        if 'Other (please specify)' in selected_elements and not other_text:
            return render_template('mid_questionnaire.html', error="Please specify what 'Other' means.",
                                   article=article, condition=condition, label_shown_ids=label_shown_ids)
        
        if "Don't know / None of these" in selected_elements and len(selected_elements) > 1:
            return render_template('mid_questionnaire.html', error="'Don't know' cannot be selected with other options.",
                                   article=article, condition=condition, label_shown_ids=label_shown_ids)
        
        if selected_elements == ['Other (please specify)']:
            selected_elements = [f"Other: {other_text}"]

        trust_article = request.form.get('trust_article')
        trust_image = request.form.get('trust_image')

        update_participant_data('round', {
            'round': session.get('round', 1),
            'article_id': article_id,
            'mid_questionnaire': {
                'selected_elements': selected_elements,
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
        label_shown_ids=label_shown_ids
    )





@app.route('/post-questionnaire', methods=['GET', 'POST'])
@require_previous_step('mid_questionnaire')
def post_questionnaire():
    if request.method == 'POST':
        # confidence = request.form.get('confidence')
        # score_meaning = request.form.getList('score_meaning')
        # score_meaning_other = request.form.get('score_meaning_other')
        # label_expectation = request.form.getlist('label_expectation')
        # label_expectation_other = request.form.get('label_expectation_other')
        # grade_basis = request.form.get('grade_basis')
        # grade_basis_other = request.form.get('grade_basis_other')
        # # label_opinion = request.form.get('label_opinion')
        # attention_check = request.form.get('attention_check')
        # feedback = request.form.get('feedback')

        confidence = request.form.get('confidence')
        score_meaning = request.form.getlist('score_meaning')
        score_meaning_other = request.form.get('score_meaning_other')
        label_expectation = request.form.getlist('label_expectation')
        label_expectation_other = request.form.get('label_expectation_other')
        grade_basis = request.form.get('grade_basis')
        grade_basis_other = request.form.get('grade_basis_other')
        # label_opinion = request.form.get('label_opinion')
        feedback = request.form.get('feedback')

        # Likert-scale responses
        likert_items = ['understood_label', 'visual_design', 'decision_support', 'info_usefulness',
                        'image_trust', 'evaluate_trustworthiness', 'more_labels', 'attention_check']

        likert_responses = {}
        for item in likert_items:
            val = request.form.get(item)
            if not val:
                return render_template('post_questionnaire.html', error="Please answer all Likert-scale questions.")
            likert_responses[item] = int(val)


        if not all([confidence, score_meaning, grade_basis, likert_responses]):
            return render_template('post_questionnaire.html', error="Please answer all required questions.")
        if not label_expectation:
            return render_template('post_questionnaire.html', error="Please select at least one option for question 2.")
        if score_meaning == "Something else (please say what)":
            score_meaning = f"Other: {score_meaning_other}"
        if grade_basis == "Something else (please say what)":
            grade_basis = f"Other: {grade_basis_other}"
        if "Other" in label_expectation and label_expectation_other:
            label_expectation = [
                f"Other: {label_expectation_other}" if v == "Other" else v
                for v in label_expectation
            ]
        update_participant_data('post_questionnaire', {
            # 'confidence': confidence,
            # 'feedback': feedback,
            # 'score_meaning': score_meaning,
            # 'label_expectation': label_expectation,
            # 'grade_basis': grade_basis,
            # # 'label_opinion': label_opinion,
            # 'attention_check': attention_check,
            # 'label_present': session.get('last_article_had_label', False)
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
            'grade_basis': f"Other: {grade_basis_other}" if grade_basis == "Other" and grade_basis_other else grade_basis,
            'likert_responses': likert_responses,
            'label_present': session.get('last_article_had_label', False)
        })
        session['post_questionnaire_completed'] = True
        return redirect(url_for('thank_you'))
    return render_template('post_questionnaire.html')

@app.route('/thank-you')
@require_previous_step('post_questionnaire')
def thank_you():
    condition = session.get('condition', 'none')
    return render_template('thank_you.html', condition=condition)

if __name__ == '__main__':
    app.run(debug=True)
