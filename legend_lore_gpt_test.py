import argparse
import json
import requests
import requests.auth
import praw
import sys
import datetime
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
        help="Name of subreddit to parse, e.g. 'r/battlemaps'",
    )  # Specify subreddit for parsing
    # -h / --help exists by default and prints prog, description, epilog

    args = parser.parse_args()

    return [args.database, args.subreddit]


def main():

    # Handle script arguments
    db_name, subreddit = parse_args()

    # reddit.send_recent_posts_to_db("battlemaps")
    # reddit.send_recent_posts_to_db("dndmaps")
    # reddit.send_recent_posts_to_db("FantasyMaps")
    # reddit.send_recent_posts_to_db("dungeondraft")
    # reddit.send_recent_posts_to_db("inkarnate")

    # all_subreddit_posts = mongodb_local.get_all_posts_from_db("all").sort_values(
    #     by=["created_time"], ascending=False
    # )

    all_subreddit_posts = mongodb_local.get_all_posts_from_db("gpt_test").sort_values(
        by=["created_time"], ascending=False
    )

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
    # notion_titles_list = [
    #     page["properties"]["Name"]["title"][0]["text"]["content"]
    #     for page in notion_map_database
    # ]

    database_client = mongodb_local.get_database_client(CONNECTION_STRING, DB_NAME)
    database_gpt4v = database_client["gpt_test"]

    for index, post in all_subreddit_posts.iterrows():
        # Analyze and tag maps
        gpt4v_api.analyze_and_tag_post(post, append=False)
        mongodb_local.reset_post_tags(
            post, subreddit="gpt4v_test", database=database_gpt4v
        )

        # notion.send_to_notion(
        #     post,
        #     overwrite=False,
        #     notion_map_database=notion_map_database,
        #     notion_titles_list=notion_titles_list,
        # )
        # pass


if __name__ == "__main__":
    main()
