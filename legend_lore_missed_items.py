import argparse
import json
import requests
import requests.auth
import concurrent.futures
import praw
import sys
import datetime
import threading
import time
import traceback
import mongodb_local
import reddit
import notion
import gpt4v_api
from time import sleep
from pymongo import MongoClient
from config import (
    APP_NAME,
    APP_VERSION,
    DB_NAME,
    DEFAULT_SUBREDDIT,
    CREDENTIALS_FILE,
    CONNECTION_STRING,
    DB_NAME,
    TAGS,
    SUBREDDITS,
)


def parse_args():
    parser = argparse.ArgumentParser(
        prog="Map Sorter - Reddit Edition",
        description="A project that uses AI vision to organize publicly available TTRPG maps by tag, helping you search for the perfect map!",
        epilog="To submit bug reports, contribute, etc., see https://github.com/EpicRandomGuy2/LegendLore.",
    )

    parser.add_argument(
        "-d", "--database", default=DB_NAME, help="MongoDB database name"
    )  # Specify MongoDB database name
    parser.add_argument(
        "-s",
        "--subreddit",
        default=DEFAULT_SUBREDDIT,
        help="Name of subreddit to parse, e.g. 'battlemaps'",
    )  # Specify subreddit for parsing
    # -h / --help exists by default and prints prog, description, epilog

    args = parser.parse_args()

    return [args.database, args.subreddit]


def main():

    # Handle script arguments
    db_name, subreddit = parse_args()

    all_subreddit_posts = mongodb_local.get_untagged_posts_from_db("all").sort_values(
        by=["created_time"], ascending=True
    )

    print(len(all_subreddit_posts))

    for index, post in all_subreddit_posts.iterrows():
        # Analyze and tag maps
        # Skip if error, these calls cost money
        try:
            # mongodb_local.reset_post_tags(post, subreddit="gpt_test")
            gpt4v_api.analyze_untagged_post(post, append=False)

            # After tagging, we need to update the post for it to send to Notion
            post = mongodb_local.get_post_from_db(post["title"]).iloc[0].to_dict()
        except Exception as e:
            print(f"Tagging error occurred on {post['title']}, skipping...")
            print(e)
            # Inform me and keep going, do not send to Notion
            print(traceback.format_exc())
            continue


if __name__ == "__main__":
    main()
