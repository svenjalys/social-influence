from flask import Flask, render_template, request, redirect, url_for, session
import pandas as pd
import json
import os
import random
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key'

@app.before_request
def assign_condition():
    if 'condition' not in session:
        os.makedirs('responses', exist_ok=True)
        try:
            with open(RESPONSES_FILE, 'r') as f:
                all_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            all_data = {}

        existing_participants = list(all_data.keys())
        idx = len(existing_participants) % 3
        conditions = ['color', 'no_color', 'c2pa']
        session['condition'] = conditions[idx]

@app.route('/set-condition/<cond>')
def set_condition(cond):
    if cond in ['color', 'no_color', 'c2pa']:
        session['condition'] = cond
        return f"Condition set to {cond}. <a href='/select-article'>Continue</a>"
    return "Invalid condition", 400


RESPONSES_FILE = "responses/responses.json"
df = pd.read_csv("articles.csv")
df.reset_index(inplace=True)

def get_participant_id():
    if 'participant_id' not in session:
        session['participant_id'] = f"participant_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return session['participant_id']

def update_participant_data(section, data):
    os.makedirs('responses', exist_ok=True)
    pid = get_participant_id()
    if os.path.exists(RESPONSES_FILE):
        with open(RESPONSES_FILE, 'r') as f:
            all_data = json.load(f)
    else:
        all_data = {}

    if pid not in all_data:
        all_data[pid] = {
            'participant_id': pid,
            'condition': session.get('condition', 'unknown')
        }

    if section == 'round':
        all_data[pid].setdefault('rounds', []).append(data)
    else:
        all_data[pid][section] = data

    with open(RESPONSES_FILE, 'w') as f:
        json.dump(all_data, f, indent=4)


@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/demographics', methods=['GET', 'POST'])
def demographics():
    if request.method == 'POST':
        gender = request.form.get('gender')
        gender_self = request.form.get('gender_self_describe')
        age_group = request.form.get('age_group')
        country = request.form.get('country')
        other_country = request.form.get('other_country')
        occupation = request.form.get('occupation')
        other_occupation = request.form.get('other_occupation')

        if gender == 'Self-describe':
            gender = gender_self.strip() if gender_self else 'Self-describe'
        if country == 'Other':
            country = other_country.strip() if other_country else 'Other'
        if occupation == 'Other':
            occupation = other_occupation.strip() if other_occupation else 'Other'
        if age_group == '15 or younger':
            return render_template('thank_you.html', message="Sorry, you do not meet the age criteria for this study.")

        update_participant_data('demographics', {
            'gender': gender,
            'age_group': age_group,
            'country': country,
            'occupation': occupation
        })

        session['round'] = 1
        return redirect(url_for('pre_questionnaire'))
    return render_template('demographics.html')

@app.route('/pre-questionnaire', methods=['GET', 'POST'])
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
        session['round'] = 1
        return redirect(url_for('select_article'))
    return render_template('pre_questionnaire.html')

@app.route('/select-article', methods=['GET', 'POST'])
def select_article():
    if request.method == 'POST':
        selected_article_id = int(request.form['selected_article_id'])
        session['next_article'] = selected_article_id

        # Use DataFrame directly to ensure valid fields
        article_row = df[df['index'] == selected_article_id]
        if not article_row.empty:
            article = article_row.iloc[0]
            update_participant_data('theme_selection', {
                'selected_article_id': selected_article_id,
                'selected_article_title': article['Title'],
                'selected_article_category': article['Category'],
                'condition': session.get('condition', 'unknown')
            })
        else:
            update_participant_data('theme_selection', {
                'selected_article_id': selected_article_id,
                'selected_article_title': None,
                'selected_article_category': None,
                'condition': session.get('condition', 'unknown')
            })

        return redirect(url_for('article', article_id=selected_article_id))

    # GET: select 4 articles from different categories
    grouped = df.groupby(df['Category'].str.title())
    selected_categories = random.sample(list(grouped.groups), k=min(4, len(grouped)))

    selected_articles = []
    for cat in selected_categories:
        selected_article = grouped.get_group(cat).sample(1).iloc[0]
        selected_articles.append(selected_article)

    article_dicts = []
    for a in selected_articles:
        article_dict = a.to_dict()
        article_dict['index'] = int(a['index'])  # ensure index is included
        article_dicts.append(article_dict)

    # Show label for all
    label_ids = [a['index'] for a in article_dicts]
    session['theme_articles'] = article_dicts
    session['theme_label_ids'] = label_ids

    return render_template('select_article.html', articles=article_dicts, label_ids=label_ids, condition=session['condition'])








@app.route('/article/<int:article_id>', methods=['GET', 'POST'])
def article(article_id):
    if article_id >= len(df):
        return redirect(url_for('select_article'))

    article_data = df.iloc[article_id].to_dict()

    # Recommended articles (4) from the same category
    recommendations_df = df[(df['Category'] == article_data['Category']) & (df['index'] != article_id)]
    recommendations = recommendations_df.sample(min(4, len(recommendations_df))).to_dict(orient='records')

    # Randomly assign 2 labels
    label_shown_ids = set(random.sample([rec['index'] for rec in recommendations], min(2, len(recommendations))))
    session['label_shown_ids'] = [int(i) for i in label_shown_ids]

    if request.method == 'POST':
        selected_article_id = int(request.form['selected_article_id'])
        session['next_article'] = selected_article_id

        # Retrieve from form instead of inferring
        label_explained = request.form.get('label_explained') == 'true'
        selected_article_had_label = request.form.get('selected_article_had_label') == 'true'

        update_participant_data('round', {
            'round': session.get('round', 1),
            'selected_article_id': selected_article_id,
            'selected_article_title': df.iloc[selected_article_id]['Title'],
            'selected_article_category': df.iloc[selected_article_id]['Category'],
            'selected_article_had_label': selected_article_had_label,
            'label_explained': label_explained
        })

        return redirect(url_for('mid_questionnaire'))

    return render_template('article.html',
                           article=article_data,
                           recommendations=recommendations,
                           label_shown_ids=label_shown_ids,
                           condition=session['condition'])







@app.route('/mid-questionnaire', methods=['GET', 'POST'])
def mid_questionnaire():
    if request.method == 'POST':
        selected_elements = request.form.getlist('choice_elements')
        other_text = request.form.get('other_element')

        if not selected_elements:
            return render_template('mid_questionnaire.html', error="Please select at least one element that influenced your choice.")

        other_selected = 'Other (please specify)' in selected_elements
        none_selected = "Don't know / None of these" in selected_elements

        if other_selected and not other_text:
            return render_template('mid_questionnaire.html', error="Please specify what 'Other' means.")
        if none_selected and len(selected_elements) > 1:
            return render_template('mid_questionnaire.html', error="'Don't know' cannot be selected with other options.")
        if other_selected and len(selected_elements) == 1:
            selected_elements = [f"Other: {other_text}"]

        trust_article = request.form.get('trust_article')
        trust_image = request.form.get('trust_image')

        update_participant_data('round', {
            'round': session.get('round', 1),
            'article_id': session.get('next_article'),
            'mid_questionnaire': {
                'selected_elements': selected_elements,
                'trust_article': trust_article,
                'trust_image': trust_image
            }
        })

        if session.get('round', 1) < 3:
            session['round'] += 1
            return redirect(url_for('article', article_id=session.get('next_article')))
        else:
            return redirect(url_for('post_questionnaire'))

    return render_template('mid_questionnaire.html')

@app.route('/post-questionnaire', methods=['GET', 'POST'])
def post_questionnaire():
    if request.method == 'POST':
        # Get all values
        confidence = request.form.get('confidence')
        score_meaning = request.form.get('score_meaning')
        label_expectation = request.form.getlist('label_expectation')
        grade_basis = request.form.get('grade_basis')
        label_opinion = request.form.get('label_opinion')
        attention_check = request.form.get('attention_check')  # no longer validated
        feedback = request.form.get('feedback')  # optional

        # Validate required fields (except feedback)
        if not all([confidence, score_meaning, grade_basis, label_opinion, attention_check]):
            return render_template('post_questionnaire.html', error="Please answer all required questions.")
        
        if len(label_expectation) == 0:
            return render_template('post_questionnaire.html', error="Please select at least one option for question 2.")

        # Save everything (including attention_check)
        update_participant_data('post_questionnaire', {
            'confidence': confidence,
            'feedback': feedback,
            'score_meaning': score_meaning,
            'label_expectation': label_expectation,
            'grade_basis': grade_basis,
            'label_opinion': label_opinion,
            'attention_check': attention_check,
            'label_present': session.get('last_article_had_label', False)
        })

        return redirect(url_for('thank_you'))

    return render_template('post_questionnaire.html')


@app.route('/thank-you')
def thank_you():
    return render_template('thank_you.html')

if __name__ == '__main__':
    app.run(debug=True)
