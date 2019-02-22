import os
import json
from time import time
from datetime import datetime, timedelta
from collections import Counter

# Apache Airflow
from airflow import DAG
from airflow.operators.dummy_operator import DummyOperator
from airflow.operators.python_operator import PythonOperator

# Newspaper3k
import newspaper
from newspaper import Article

# Quilt
import t4

default_args = {
    'owner': 'robnewman',
    'depends_on_past': False,
    'start_date': datetime(2019, 1, 1),
    'email': ['robertlnewman@gmail.com'],
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'provide_context':True
}

# DAG
dag = DAG(
    'headlines',
    default_args=default_args,
    schedule_interval=timedelta(days=1))

# Operators
def scrape_articles(**kwargs):
    """
    Scrape articles from one or more online newspaper sources

    Parameters
    ----------
    kwargs : dict
        Dictionary that contains all keyword arguments & values

    Returns
    -------
    sources_keywords : dict
        List of all keywords generated per source
    """
    sources = kwargs['source_urls']
    category = kwargs['category']

    sources_keywords = dict()

    print(f"Scrape headlines from {len(sources)} sources that include '{category}' in the url")
    for s in sources:
        print(f"START: Scrape articles from '{s}'")
        print(f"START: Build newspaper")
        paper = newspaper.build(
            s,
            memoize_articles=False # Don't cache articles
        )
        print(f"END: Build newspaper")
        keywords_list = list()
        print("START: Collect articles")
        for article in paper.articles:
            if category in article.url:
                print(article.url)
                single_article = Article(article.url)
                single_article.download()
                count = 0
                while single_article.download_state != 2:
                    # ArticleDownloadState.SUCCESS is 2 
                    count = count+1
                    time.sleep(count)
                single_article.parse()
                single_article.nlp()
                keywords_list.extend(single_article.keywords)
        sources_keywords[s] = Counter(keywords_list)
        print("END: Collect articles")
        print(f"END: Scrape articles from '{paper}'")
    return sources_keywords

def write_to_json(**context):
    """
    Write keywords generated by NLP to local JSON file

    Parameters
    ----------
    context : dict
        Context object that contains kwargs and Xcom data

    Returns
    -------
    status : boolean
        Status of writing sentiment to disk
    """
    data_directory = context['directory']
    file_name = context['filename']
    keywords = context['task_instance'].xcom_pull(task_ids='scrape_articles')
    file_names = list()
    for k in keywords:
        # Strip leading 'https://' and trailing '.com'
        domain = k.replace("https://","")
        domain = domain.replace(".com", "")
        new_fname = f"{data_directory}/{domain}_{file_name}"
        file_names.append(new_fname)
        with open(new_fname, 'w') as f:
            json.dump(
                keywords[k],
                f,
                ensure_ascii=False,
                indent=2,
                sort_keys=True
            )
    return file_names

def add_to_package(**context):
    """
    Add JSON file to Quilt T4 package

    Parameters
    ----------
    context : dict
        Context object that contains Xcom data

    Returns
    -------
    status : boolean
        Status of add file to package
    """    
    datafiles = context['task_instance'].xcom_pull(task_ids='write_to_json')
    p = t4.Package()
    for df in datafiles:
        p = p.set(
            df,
            f"{os.getcwd()}/{df}",
            meta=f"Add source file from {datetime.today().strftime('%Y-%m-%d')}"
        )
    tophash = p.build("robnewman/sentiment-analysis-headlines")
    p.push(
        "robnewman/sentiment-analysis-headlines",
        dest="s3://alpha-quilt-storage/sentiment-analysis-headlines",
        message=f"Source data from {datetime.today().strftime('%Y-%m-%d')}"
    )
    return True

# Tasks
task1 = PythonOperator(
    task_id='scrape_articles',
    python_callable=scrape_articles,
    op_kwargs={
        'source_urls': [
            'https://theguardian.com',
            'https://nytimes.com',
            'https://cnn.com'
        ],
        'category': 'politics'
    },
    dag=dag
)

task2 = PythonOperator(
    task_id='write_to_json',
    python_callable=write_to_json,
    op_kwargs={
        'directory': 'data',
        'filename': 'keywords.json'
    },
    dag=dag
)

task3 = PythonOperator(
    task_id='add_to_package',
    python_callable=add_to_package,
    dag=dag
)

# Set dependencies
task1 >> task2 >> task3