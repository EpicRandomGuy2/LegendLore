import sys
from pymongo import MongoClient
from pandas import DataFrame
from config import CONNECTION_STRING, DB_NAME, DEFAULT_SUBREDDIT, SUBREDDITS


def get_database_client(connection_string=CONNECTION_STRING, db_name=DB_NAME):

    client = MongoClient(connection_string)

    return client[db_name]


def post_in_db(
    post_title,
    subreddit=DEFAULT_SUBREDDIT,
    connection_string=CONNECTION_STRING,
    db_name=DB_NAME,
    database=None,  # I think passing the database makes it go a little faster?
):
    if database == None:
        database_client = get_database_client(connection_string, db_name)
        database = database_client[subreddit]

    # Check to ensure post is unique in DB
    query = {"title": post_title}

    if DataFrame(database.find(query)).empty:
        return False
    else:
        return True


def post_id_in_db(
    post_id,
    subreddit=DEFAULT_SUBREDDIT,
    connection_string=CONNECTION_STRING,
    db_name=DB_NAME,
    database=None,  # I think passing the database makes it go a little faster?
):
    if database == None:
        database_client = get_database_client(connection_string, db_name)
        database = database_client[subreddit]

    # Check to ensure post is unique in DB
    query = {"post_id": post_id}

    if DataFrame(database.find(query)).empty:
        return False
    else:
        return True


def add_post_to_db(
    post,
    subreddit=DEFAULT_SUBREDDIT,
    connection_string=CONNECTION_STRING,
    db_name=DB_NAME,
    database=None,
):

    if database == None:
        database_client = get_database_client(connection_string, db_name)
        database = database_client[subreddit]

    if not post_in_db(post["title"], subreddit, connection_string, db_name):
        print(f"Adding {post['title']} to MongoDB...")
        database.insert_one(post)
    else:
        print(f"{post['title']} is already in MongoDB, skipping...")


def add_tags_to_post(
    post,
    tags,
    subreddit=DEFAULT_SUBREDDIT,
    connection_string=CONNECTION_STRING,
    db_name=DB_NAME,
    database=None,
):

    if database == None:
        database_client = get_database_client(connection_string, db_name)
        database = database_client[subreddit]

    query = {"title": post["title"]}

    post_df = DataFrame(database.find(query))

    for tag in tags:

        # Add a tag if it is not already in the tags array, else keep it the same (to prevent duplicate tags)
        post_df["tags"] = post_df["tags"].apply(
            lambda tags: tags + [tag] if tag not in tags else tags
        )

        # Update any matching items in the query (should only be 1)
        for index, row in post_df.iterrows():
            # print(row["tags"])
            query = {"_id": row["_id"]}
            new = {"$set": {"tags": row["tags"]}}
            database.update_many(query, new)

        # print(f"Tag {tag} added to {post_df['title']}")


def reset_post_tags(
    post,
    subreddit=DEFAULT_SUBREDDIT,
    connection_string=CONNECTION_STRING,
    db_name=DB_NAME,
    database=None,
):
    if database == None:
        database_client = get_database_client(connection_string, db_name)
        database = database_client[subreddit]

    confirm = input(
        f"You are about to reset tags for {post['title']}. This process cannot be undone.\n \
                Type RESET TAGS to continue: "
    )

    while confirm != "RESET TAGS":
        confirm = input(
            "Incorrect input.\n \
                Type RESET TAGS to continue: "
        )

    query = {"title": post["title"]}

    post_df = DataFrame(database.find(query))

    # Update any matching items in the query (should only be 1)
    for index, row in post_df.iterrows():
        query = {"_id": row["_id"]}
        new = {"$set": {"tags": []}}
        database.update_many(query, new)

    # print(f"Tags removed from {post_df['title']}")


def reset_sent_to_notion(
    subreddits=SUBREDDITS,
    connection_string=CONNECTION_STRING,
    db_name=DB_NAME,
    database=None,
):
    confirm = input(
        "You are about to set sent_to_notion to False for all MongoDB entries. This will cause the database to lose state with Notion, and require a full Notion rebuild (3+ days).\n \
                Type RESET NOTION to continue: "
    )

    while confirm != "RESET NOTION":
        confirm = input(
            "Incorrect input.\n \
                Type RESET NOTION to continue: "
        )

    for subreddit in subreddits:
        database_client = get_database_client(connection_string, db_name)
        database = database_client[subreddit]

        query = {}
        new = {"$set": {"sent_to_notion": False}}
        database_client[subreddit].update_many(query, new)


def set_sent_to_notion(
    post,
    sent=True,
    subreddit=DEFAULT_SUBREDDIT,
    connection_string=CONNECTION_STRING,
    db_name=DB_NAME,
    database=None,
):

    if database == None:
        database_client = get_database_client(connection_string, db_name)
        database = database_client[subreddit]

    # Check to ensure post is unique in DB
    query = {"title": post["title"]}

    post_df = DataFrame(database.find(query))

    # Update anything matching those keys in the query
    for index, row in post_df.iterrows():
        query = {"_id": row["_id"]}
        new = {"$set": {"sent_to_notion": sent}}
        database.update_many(query, new)
        database_client["all"].update_many(query, new)

        # print(f"sent_to_notion {sent} added to {post_df['title']}")


def get_post_from_db(
    post_title,
    subreddit=DEFAULT_SUBREDDIT,
    connection_string=CONNECTION_STRING,
    db_name=DB_NAME,
    database=None,
):
    if database == None:
        database_client = get_database_client(connection_string, db_name)
        database = database_client[subreddit]

    # Check to ensure post is unique in DB
    query = {"title": post_title}

    return DataFrame(database.find(query))


def get_all_posts_from_db(
    subreddit=DEFAULT_SUBREDDIT,
    connection_string=CONNECTION_STRING,
    db_name=DB_NAME,
    database=None,
):
    if database == None:
        database_client = get_database_client(connection_string, db_name)
        database = database_client[subreddit]

    # Adding this filter to remove things with a score of 0 - they are usually spam or low-effort, downvoted posts (not maps)
    # Necessary to filter out dirty images, even if we miss a couple maps
    return DataFrame(database.find({"score": {"$gte": 1}}))
