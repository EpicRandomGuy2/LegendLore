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
    NUMBER_OF_DAYS_OLD,
    UPDATE_SCORES_LIMIT,
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
    parser.add_argument(
        "-u",
        "--update-scores",
        action="store_true",
        help="Set to update the scores of the most recent 500 posts",
    )  # Specify subreddit for parsing
    # -h / --help exists by default and prints prog, description, epilog

    args = parser.parse_args()

    return [args.database, args.subreddit, args.update_scores]


def post_older_than(post, days=7):
    print(post["created_time"])
    created_time = datetime.datetime.fromtimestamp(post["created_time"])

    current_time = datetime.datetime.now()

    number_of_days_ago = current_time - datetime.timedelta(days=days)

    if created_time < number_of_days_ago:
        return True
    else:
        return False


def main():

    # Handle script arguments
    db_name, subreddit_name, update_scores = parse_args()

    # To-do: Trigger script on new post to any of the subs

    # mongodb_local.reset_sent_to_notion()

    for subreddit in SUBREDDITS:
        reddit.send_recent_posts_to_db(subreddit)

    # reddit.send_recent_posts_to_db("battlemaps")
    # reddit.send_recent_posts_to_db("dndmaps")
    # reddit.send_recent_posts_to_db("FantasyMaps")
    # reddit.send_recent_posts_to_db("dungeondraft")
    # reddit.send_recent_posts_to_db("inkarnate")

    update_scores_limit = UPDATE_SCORES_LIMIT
    updated_score_titles = set()

    if update_scores:
        number_of_days_old = NUMBER_OF_DAYS_OLD

        for subreddit in SUBREDDITS:
            updated_score_titles.update(
                reddit.update_recent_scores_in_db(
                    subreddit,
                    limit=update_scores_limit,
                    number_of_days_old=number_of_days_old,
                )
            )

        # reddit.update_recent_scores_in_db(
        #     "battlemaps",
        #     limit=update_scores_limit,
        #     number_of_days_old=number_of_days_old,
        # )
        # reddit.update_recent_scores_in_db(
        #     "dndmaps", limit=update_scores_limit, number_of_days_old=number_of_days_old
        # )
        # reddit.update_recent_scores_in_db(
        #     "FantasyMaps",
        #     limit=update_scores_limit,
        #     number_of_days_old=number_of_days_old,
        # )
        # reddit.update_recent_scores_in_db(
        #     "dungeondraft",
        #     limit=update_scores_limit,
        #     number_of_days_old=number_of_days_old,
        # )
        # reddit.update_recent_scores_in_db(
        #     "inkarnate",
        #     limit=update_scores_limit,
        #     number_of_days_old=number_of_days_old,
        # )

    # Top x posts, cause we need to update scores too. Also need to cut this so it doesn't run the whole DB (while skipping everything after the first few values)
    # Ascending=True means newest first -> oldest last, False is oldest first -> newest last
    # Reversing it to keep the created_time order.
    # Never update more than the max possible number of scores that were updated.
    all_subreddit_posts = mongodb_local.get_all_posts_from_db("all").sort_values(
        by=["created_time"], ascending=False
    )[: update_scores_limit * len(SUBREDDITS)][
        ::-1
    ]  # [::-1]

    # To-do: Figure out the score issue - other than waiting a week to update, I'm not sure how to get/update the scores. Should I just update all scores less than a week old? Will increase runtime a lot.

    print(len(all_subreddit_posts))

    count = 0

    for index, post in all_subreddit_posts.iterrows():
        # Skip if the post is older than 7 days, cause it didn't even get updated score
        # and updating a Notion post takes a long time
        # if post_older_than(post, days=7):
        #     continue

        # Analyze and tag maps
        # Skip if error, these calls cost money
        try:
            print(count)
            # mongodb_local.reset_post_tags(post, subreddit="gpt_test")
            # Analyzes post, and if it comes out untagged, second function tries to tag it by passing in a higher res image

            gpt4v_api.analyze_and_tag_post(post, append=False)
            gpt4v_api.analyze_untagged_post(post, append=False)

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
                notion.send_to_notion(
                    post,
                    overwrite=False,
                    update_score=update_scores,
                    updated_score_titles=updated_score_titles,
                )

                break
            except Exception as e:
                print(f"Error occurred on {post['title']}...")
                print(e)
                print(traceback.format_exc())
                print(f"Trying {post['title']} again (Attempt {attempts})...")
                attempts += 1
                sleep(10)

        # break # Break after one map

        count += 1


if __name__ == "__main__":
    main()
