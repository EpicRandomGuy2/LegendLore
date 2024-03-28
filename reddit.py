import json
import praw
import datetime
import mongodb_local
from time import sleep
from config import (
    APP_NAME,
    APP_VERSION,
    DB_NAME,
    DEFAULT_SUBREDDIT,
    CREDENTIALS_FILE,
    CONNECTION_STRING,
    DB_NAME,
)


def get_subreddit_posts(
    subreddit=DEFAULT_SUBREDDIT,
    limit=None,
    update=False,
    number_of_days_old=None,
    credentials=CREDENTIALS_FILE,
):

    # https://praw.readthedocs.io/en/stable/getting_started/quick_start.html

    with open(credentials) as credentials_json:
        credentials = json.load(credentials_json)

    # Initialize authorized Reddit instance using personal creds and app secrets from credentials.json
    reddit = praw.Reddit(
        username=credentials["reddit_username"],
        password=credentials["reddit_password"],
        client_id=credentials["reddit_client_id"],
        client_secret=credentials["reddit_client_secret"],
        user_agent=f"{APP_NAME}/{APP_VERSION} by {credentials['reddit_username']}",
        ratelimit_seconds=600,
    )

    reddit.read_only = True

    subreddit_posts = []

    subreddit_new = reddit.subreddit(subreddit).new(limit=limit)

    # Generally a 1000 post limit - not a PRAW issue, a Reddit one - How can I get more?
    # Could at least pre-populate the subs with top 1000 of all time
    # https://psaw.readthedocs.io/en/latest/ might be able to do it, maintains its own link database?

    try:
        for post in subreddit_new:
            if update == False and mongodb_local.post_id_in_db(post.id, subreddit):
                break

            if number_of_days_old != None:

                created_time = datetime.datetime.fromtimestamp(post.created_utc)

                current_time = datetime.datetime.now()

                number_of_days_ago = current_time - datetime.timedelta(
                    days=number_of_days_old
                )

                if created_time < number_of_days_ago:
                    break

            post_data = {
                "permalink": post.permalink,
                "url": post.url,
                "title": post.title,
                "subreddit": post.subreddit.display_name,
                "author": f"u/{post.author}",
                "created_time": str(datetime.datetime.fromtimestamp(post.created_utc)),
                "post_id": post.id,
                "score": post.score,
                "text": post.selftext,
                "comments": [],
                "tags": [],
                "sent_to_notion": False,
            }

            try:
                post_data["media_metadata"] = post.media_metadata
            except AttributeError:
                pass

            for comment in post.comments:
                # If it's a top level comment made by OP
                if (
                    comment.parent_id == f"t3_{post_data['post_id']}"
                    and comment.is_submitter
                ):
                    post_data["comments"].append(comment.body)

            subreddit_posts.append(post_data)
            # print(post_data)
            # sleep(2)
    except Exception as e:
        print(e)
        print("Probably hit a rate limit, continuing with what we've got...")

    return subreddit_posts


def get_one_subreddit_post(
    post_id, subreddit=DEFAULT_SUBREDDIT, limit=None, credentials=CREDENTIALS_FILE
):

    # https://praw.readthedocs.io/en/stable/getting_started/quick_start.html

    with open(credentials) as credentials_json:
        credentials = json.load(credentials_json)

    # Initialize authorized Reddit instance using personal creds and app secrets from credentials.json
    reddit = praw.Reddit(
        username=credentials["reddit_username"],
        password=credentials["reddit_password"],
        client_id=credentials["reddit_client_id"],
        client_secret=credentials["reddit_client_secret"],
        user_agent=f"{APP_NAME}/{APP_VERSION} by {credentials['reddit_username']}",
    )

    reddit.read_only = True

    try:
        post = reddit.submission(post_id)
        sleep(2)  # 30 requests per minute rate limit
    except Exception as e:
        print("Too many requests, backing off for 2 seconds")
        sleep(10)
        return get_one_subreddit_post(post_id)

    post_data = {
        "permalink": post.permalink,
        "url": post.url,
        "title": post.title,
        "subreddit": post.subreddit.display_name,
        "author": f"u/{post.author}",
        "created_time": str(datetime.datetime.fromtimestamp(post.created_utc)),
        "post_id": post.id,
        "score": post.score,
        "text": post.selftext,
        "comments": [],
        "tags": [{"name": str(post.author)}],
    }

    try:
        post_data["media_metadata"] = post.media_metadata
    except AttributeError:
        pass

    for comment in post.comments:
        # If it's a top level comment made by OP
        try:
            if (
                comment.parent_id == f"t3_{post_data['post_id']}"
                and comment.is_submitter
            ):
                post_data["comments"].append(comment.body)
        except AttributeError as e:
            continue  # Apparently there is a literal 1 in 20,000 chance for is_submitter to be missing

    return post_data


def send_historical_posts_to_db(subreddit=DEFAULT_SUBREDDIT):

    # Get database client
    mongodb_client = mongodb_local.get_database_client()

    print(mongodb_client)

    with open(f"./pushshift/json/{subreddit}_2024.json", "r") as file_json:
        all_posts_json = json.load(file_json)

        # Do this twice for some reason - first load turns it to a string, loads turns it to dict
        # all_posts_json = json.loads(all_posts_json)

        # print(all_posts_json["submissions"][-1])

        subreddit_posts = []

        database_client = mongodb_local.get_database_client(CONNECTION_STRING, DB_NAME)
        database_subreddit = database_client[subreddit]
        database_all = database_client["all"]

        # [26900:] Indexing to restart from position
        for post in all_posts_json["submissions"]:
            # print(get_one_subreddit_post(post["id"]))
            # Check to ensure post is unique in DB
            # Then send to subreddit collection and all collection
            # This is how to prevent dedupes across subs
            if not mongodb_local.post_in_db(post["title"], "all"):
                post = get_one_subreddit_post(post["id"])
                mongodb_local.add_post_to_db(
                    post, post["subreddit"], database=database_subreddit
                )
                mongodb_local.add_post_to_db(post, "all", database=database_all)
            else:
                print(f"{post['title']} is already in MongoDB, skipping...")


def send_recent_posts_to_db(subreddit=DEFAULT_SUBREDDIT, limit=None):

    print(f"Fetching latest posts from r/{subreddit} and sending to MongoDB...")

    # battlemaps
    # dndmaps
    # fantasymaps
    # inkarnate
    # dungeondraft
    subreddit_posts = get_subreddit_posts(subreddit=subreddit, limit=limit)
    print(len(subreddit_posts))

    # Get database client
    database_client = mongodb_local.get_database_client(CONNECTION_STRING, DB_NAME)
    database_subreddit = database_client[subreddit]
    database_all = database_client["all"]

    print(database_client)

    # Add maps to database (skip duplicates)
    for post in subreddit_posts:
        # if not mongodb_local.post_in_db(post["title"], "all"):
        mongodb_local.add_post_to_db(
            post, post["subreddit"], database=database_subreddit
        )
        mongodb_local.add_post_to_db(post, "all", database=database_all)
        # else:
        #     print(f"{post['title']} is already in MongoDB, skipping...")


def update_recent_scores_in_db(
    subreddit=DEFAULT_SUBREDDIT, limit=None, number_of_days_old=7
):

    print(
        f"Fetching posts from r/{subreddit} less than {number_of_days_old} days old and sending new scores to MongoDB..."
    )

    # battlemaps
    # dndmaps
    # fantasymaps
    # inkarnate
    # dungeondraft
    subreddit_posts = get_subreddit_posts(
        subreddit=subreddit,
        limit=limit,
        update=True,
        number_of_days_old=number_of_days_old,
    )
    print(len(subreddit_posts))

    # Get database client
    database_client = mongodb_local.get_database_client(CONNECTION_STRING, DB_NAME)
    database_subreddit = database_client[subreddit]
    database_all = database_client["all"]

    print(database_client)

    # If the score gets updated, add it to this list so we can
    # process them faster later

    updated_score_titles = set()

    # Add maps to database (skip duplicates)
    for post in subreddit_posts:
        # if not mongodb_local.post_in_db(post["title"], "all"):
        mongodb_local.update_post_score(
            post, post["subreddit"], database=database_subreddit
        )
        updated_score_titles.add(
            mongodb_local.update_post_score(post, "all", database=database_all)
        )
        # else:
        #     print(f"{post['title']} is already in MongoDB, skipping...")

    return updated_score_titles
