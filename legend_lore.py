import os
import argparse
import traceback
import mongodb_local
import reddit
import notion
import gpt4v_api
from time import sleep
from config import (
    DB_NAME,
    DEFAULT_SUBREDDIT,
    DB_NAME,
    SUBREDDITS,
    NUMBER_OF_DAYS_OLD,
    UPDATE_SCORES_LIMIT,
)
from name_change import NAME_CHANGE


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
        "--update-scores",
        action="store_true",
        help="Set to update the scores of the most recent 500 posts",
    )  # Specify subreddit for parsing
    parser.add_argument(
        "--update-names",
        action="store_true",
        help="Set to update the scores of the most recent 500 posts",
    )  # Specify subreddit for parsing
    # -h / --help exists by default and prints prog, description, epilog

    args = parser.parse_args()

    return [args.database, args.subreddit, args.update_scores, args.update_names]


def main():

    # Handle script arguments
    db_name, subreddit_name, update_scores, update_names = parse_args()
    env = os.getenv("ENV")  # Dev or Prod

    # To-do: Trigger script on new post to any of the subs

    # Only use this to rebuild the whole Notion database! It takes a very long time!
    # mongodb_local.reset_sent_to_notion()

    # Get all new posts that are not already in the DB
    # Stops when it finds something that's in the DB
    for subreddit in SUBREDDITS:
        reddit.send_recent_posts_to_db(subreddit)

    # Keep a unique list of titles that get updated to improve runtime
    # when sending to Notion later
    updated_score_titles = set()

    # Update all scores less than NUMBER_OF_DAYS_OLD
    # This process takes a very long time and scores stagnate after
    # a few days, so 7 is the default
    if update_scores:
        number_of_days_old = NUMBER_OF_DAYS_OLD

        for subreddit in SUBREDDITS:
            updated_score_titles.update(
                reddit.update_recent_scores_in_db(
                    subreddit,
                    limit=UPDATE_SCORES_LIMIT,
                    number_of_days_old=number_of_days_old,
                )
            )

    # Top x posts, cause we need to update scores too. Also need to cut this so it doesn't run the whole DB (while skipping everything after the first few values)
    # Reversing it to keep the created_time order (newest at the top of the DB)
    # Never update more than the max possible number of scores that were updated.
    all_subreddit_posts = mongodb_local.get_all_posts_from_db("all").sort_values(
        by=["created_time"], ascending=False
    )[: UPDATE_SCORES_LIMIT * len(SUBREDDITS)][::-1]

    # Just to keep track of script progress
    count = 0

    # Loop through the last x maps posted to the subreddits (1250 by default)
    for index, post in all_subreddit_posts.iterrows():

        # Analyze and tag maps with GPT4V API
        # Skip if error, these calls cost money (~0.3 cents per map)
        try:
            print(count)

            # Only use this to reset tags on a post (you probably don't want to do this, you'll have to pay to re-tag it)
            # mongodb_local.reset_post_tags(post, subreddit="gpt_test")

            if env == "PROD":
                # Analyzes post, and if it comes out untagged, second function tries to tag it by passing in a higher res image (costs ~1 cent per)
                gpt4v_api.analyze_and_tag_post(post, append=False)
                gpt4v_api.analyze_untagged_post(post, append=False)

            # After tagging, we need to update the post var for it to send to Notion
            post = mongodb_local.get_post_from_db(post["title"]).iloc[0].to_dict()
        except Exception as e:
            # Print error and keep going, do not send to Notion
            print(f"Tagging error occurred on {post['title']}, skipping...")
            print(e)
            print(traceback.format_exc())
            continue

        # Will try up to 5 times to send to Notion
        # Failure is a rare case, usually a network issue

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
                # If failure, wait 10 seconds and try again (up to 5 times)
                print(f"Error occurred on {post['title']}...")
                print(e)
                print(traceback.format_exc())
                print(f"Trying {post['title']} again (Attempt {attempts})...")
                attempts += 1
                sleep(10)

        count += 1

    # If creator has requested a name change in LegendLore, hit the Notion API to update
    # all instances of that name.

    if update_names == True:
        print(f"Changing {len(NAME_CHANGE)} names...")
        # Just to keep track of script progress
        count = 0
        for name in NAME_CHANGE:
            notion.send_updated_username_to_notion(name)
            print(count)
            count += 1


if __name__ == "__main__":
    main()
