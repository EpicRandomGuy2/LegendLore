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
        epilog="To submit bug reports, contribute, etc., see https://github.com/EpicRandomGuy/LegendLore.",
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

    reddit.send_recent_posts_to_db("battlemaps")
    reddit.send_recent_posts_to_db("dndmaps")
    reddit.send_recent_posts_to_db("FantasyMaps")
    reddit.send_recent_posts_to_db("dungeondraft")
    reddit.send_recent_posts_to_db("inkarnate")

    all_subreddit_posts = mongodb_local.get_all_posts_from_db("all").sort_values(
        by=["created_time"], ascending=False
    )

    # To-do: Figure out the score issue - other than waiting a week to update, I'm not sure how to get/update the scores. Should I just update all scores less than a week old? Will increase runtime a lot.

    # all_subreddit_posts = mongodb_local.get_all_posts_from_db("gpt_test").sort_values(
    #     by=["created_time"], ascending=False
    # )

    # Generate test DB
    # count = 0
    # for index, post in all_subreddit_posts.iterrows():
    #     # print(type(post), post)
    #     if count < 100:
    #         mongodb_local.add_post_to_db(post.to_dict(), subreddit="gpt_test")

    #     count += 1

    # print(all_subreddit_posts)

    # for post in all_subreddit_posts:
    #     tags = ["test", "test2"]

    # Get current Notion state for speedup
    # notion_map_database = notion.get_notion_db_state()
    # print(len(notion_map_database))
    # for page in notion_map_database:
    #     notion_titles_list = [
    #         page["properties"]["Name"]["title"][0]["text"]["content"]
    #         for page in notion_map_database
    #     ]
    # print(len(notion_titles_list))

    # sys.exit()

    # try:
    #     notion_map_database = notion.get_notion_db_state()
    #     print(len(notion_map_database))
    #     for page in notion_map_database:
    #         notion_titles_list = [
    #             page["properties"]["Name"]["title"][0]["text"]["content"]
    #             for page in notion_map_database
    #         ]
    #     print(len(notion_titles_list))

    #     # With generator, so we can work while pulling results from the API
    #     # notion_titles_list = []
    #     # notion_map_database = []
    #     # notion_map_database_generator = notion.get_notion_db_state_generator()

    #     # print("Starting Notion build thread...")

    #     # notion_build_thread = threading.Thread(
    #     #     target=notion.build_notion_titles_list,
    #     #     args=(
    #     #         notion_map_database_generator,
    #     #         notion_map_database,
    #     #         notion_titles_list,
    #     #     ),
    #     # )
    #     # notion_build_thread.start()

    #     # sleep(30)

    # except Exception as e:
    #     # If something goes wrong after waiting a literal hour for this to build we just need to push on with what we've got
    #     # There's a redundancy built into the Notion function to make sure it's not pushing dupes
    #     print(e)

    # database_client = mongodb_local.get_database_client(CONNECTION_STRING, DB_NAME)

    # Set a sent_to_notion = False tag for every post in every collection - used for prepping a new Notion DB build
    # mongodb_local.reset_sent_to_notion()

    for index, post in all_subreddit_posts.iterrows():
        # Analyze and tag maps
        # Skip if error, these calls cost money
        try:
            # mongodb_local.reset_post_tags(post, subreddit="gpt_test")
            gpt4v_api.analyze_and_tag_post(post, append=False)

            # After tagging, we need to update the post for it to send to Notion
            post = mongodb_local.get_post_from_db(post["title"]).iloc[0].to_dict()
        except Exception as e:
            print(f"Tagging error occurred on {post['title']}, skipping...")
            print(e)
            # Inform me and keep going, do not send to Notion
            print(traceback.format_exc())
            continue

        max_attempts = 5
        attempts = 1

        while attempts <= max_attempts:
            try:
                notion.send_to_notion(post, overwrite=False)

                break
            except Exception as e:
                print(f"Error occurred on {post['title']}...")
                print(e)
                print(traceback.format_exc())
                print(f"Trying {post['title']} again (Attempt {attempts})...")
                attempts += 1
                sleep(10)

        # break # Break after one map
    # notion_build_thread.join()


if __name__ == "__main__":
    main()
