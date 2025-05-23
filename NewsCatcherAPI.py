import requests
import os
from dotenv import load_dotenv
import csv
import random
from datetime import datetime
import time

load_dotenv()

# NewsCatcher API settings
#NEWS_API_KEY = os.getenv('NEWS_API_KEY')
NEWS_API_KEY = "m102RlosKZIC9AbVdg8MeyeTAGcpbQdS"
API_URL = "https://v3-api.newscatcherapi.com/api/search"

# Categories and settings
categories = ['politics', 'sports', 'technology', 'entertainment']
articles_per_category = 15

# Fetch articles from NewsCatcher API
def fetch_news_articles(category, required=15):
    seen_keys = set()
    unique_articles = []
    page = 1
    max_pages = 5  # safety limit

    while len(unique_articles) < required and page <= max_pages:
        params = {
            'q': category,
            'lang': 'en',
            'sources': 'nytimes.com, reuters.com, foxnews.com, cbsnews.com, washingtonpost.com, cnn.com',
            'sort_by': 'relevancy',
            'page_size': 100,
            'page': page,
            'include_nlp_data': True
        }

        headers = {
            'x-api-token': NEWS_API_KEY
        }

        response = requests.get(API_URL, headers=headers, params=params)
        page += 1
        time.sleep(1)  # avoid rate limits

        if response.status_code != 200:
            print(f"Error fetching page {page-1} for {category}: {response.status_code}")
            continue

        articles = response.json().get('articles', [])
        if not articles:
            break

        for article in articles:
            title = article.get('title', '').strip()
            provider = article.get('clean_url', '').strip().lower()
            unique_key = f"{title.lower()}::{provider}"

            if unique_key not in seen_keys and title:
                seen_keys.add(unique_key)
                image_url = article.get('media', '').strip()
                article_url = article.get('link', '').strip()
                content = article.get('content', 'No Content').strip()
                unique_articles.append([category, title, image_url, article_url, content, provider])

            if len(unique_articles) >= required:
                break

    if len(unique_articles) < required:
        print(f"Warning: Only {len(unique_articles)} unique articles found for category '{category}'")

    return unique_articles


# Write the articles to a CSV file
def write_articles_to_csv(articles, filename='articles.csv'):
    headers = ['Category', 'Title', 'Image URL', 'Article URL', 'Content', 'News Provider']

    with open(filename, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(headers)

        for article in articles:
            writer.writerow(article)

    print(f"Data has been written to {filename}")

# Extract one random article per category
# def extract_random_articles(filename='articles.csv', output_file='selected_articles.csv'):
#     category_articles = {}

#     with open(filename, mode='r', encoding='utf-8') as file:
#         reader = csv.DictReader(file)
#         for row in reader:
#             category = row['Category']
#             if category not in category_articles:
#                 category_articles[category] = []
#             category_articles[category].append(row)

#     selected_articles = []
#     for category in categories:
#         if category in category_articles and category_articles[category]:
#             selected_article = random.choice(category_articles[category])
#             selected_articles.append(selected_article)

#     # Write selected articles to new CSV
#     with open(output_file, mode='w', newline='', encoding='utf-8') as file:
#         writer = csv.DictWriter(file, fieldnames=['Category', 'Title', 'Image URL', 'Article URL', 'Content', 'News Provider'])
#         writer.writeheader()
#         writer.writerows(selected_articles)

#     print(f"Selected articles written to {output_file}")

# Main function
def main():
    all_articles = []
    for category in categories:
        articles = fetch_news_articles(category, required=articles_per_category)
        all_articles.extend(articles)

    if all_articles:
        write_articles_to_csv(all_articles)
    else:
        print("No unique articles found.")




if __name__ == "__main__":
    main()


