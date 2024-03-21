import os
import sys
import time
import base64
import requests
import re
import itertools
import traceback
import json
import urllib.parse
import httpx
import threading
import time
from notion_client import Client
from notion_client.helpers import collect_paginated_api
from notion_client.helpers import iterate_paginated_api
from openai import OpenAI
from bs4 import BeautifulSoup
from mongodb_local import get_database_client, get_post_from_db, set_sent_to_notion
from pandas import DataFrame
from config import DB_NAME, NOTION_DB_ID, NOTION_DB_NAME, CREDENTIALS_FILE, TAGS
from pprint import pprint


def send_to_notion(
    post,
    overwrite=False,
    subreddit=None,
    notion_map_database=None,
    notion_titles_list=None,
    credentials=CREDENTIALS_FILE,
):
    if not subreddit:
        subreddit = post["subreddit"]

    # https://developers.notion.com/reference/post-page

    # If dupe and no overwrite, skip this post
    if handle_duplicates(post, overwrite, subreddit=subreddit) == False:
        return

    with open(credentials) as credentials_json:
        credentials = json.load(credentials_json)

    token = credentials["notion_token"]

    while True:  # Try again if the query fails, a simple retry usually fixes it
        try:
            headers = {
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            }

            # Skip the GPT-4V tag, does nothing for users but is useful in MongoDB
            tags = post["tags"][:-1]
            # print(tags)

            body = {
                "parent": {"database_id": NOTION_DB_ID},
                "properties": {
                    "Name": {"title": [{"text": {"content": post["title"]}}]},
                    "Tags": {"type": "multi_select", "multi_select": tags},
                    # "Creator": {
                    #     "type": "select",
                    #     "select": {"name": post["author"].lstrip("u/")},
                    # },
                    "Creator": {
                        "type": "rich_text",
                        "rich_text": [
                            {"text": {"content": post["author"].lstrip("u/")}}
                        ],
                    },
                    "Score": {"type": "number", "number": post["score"]},
                    "Subreddit": {
                        "type": "multi_select",
                        "multi_select": [{"name": f"r/{post['subreddit']}"}],
                    },
                    "Date": {"date": {"start": post["created_time"]}},
                },
                "children": [],
            }

            # Different urls need to have embedding handled differently
            if "i.redd.it" in post["url"]:
                child = [
                    {
                        "object": "block",
                        "embed": {"url": post["url"]},
                    },
                ]

                body["children"].extend(child)
            elif "reddit.com/gallery" in post["url"]:
                # https://www.reddit.com/r/redditdev/comments/paia21/how_to_get_image_url_using_praw_instead_of_the/
                try:
                    for image in post["media_metadata"].values():
                        child = [
                            {
                                "object": "block",
                                "embed": {"url": image["s"]["u"]},
                            },
                        ]

                        body["children"].extend(child)
                # Rarely media_metadata is a float for some reason?? Or just missing.
                except (AttributeError, KeyError) as e:
                    print(f"{e}: https://www.reddit.com{post['permalink']}")
                    pass

            # Condition 4 - imgur albums /a/ , /gallery/ - This embeds in Notion but not API, may need to just get the first image, or all of them and embed them in sequence
            # Condition 4.5 - imgur embeds (non-gallery) randomly not working - fixed by getting direct link to image
            elif "imgur.com" in post["url"]:

                # Change all http links to https or Imgur 404s
                modified_url = post["url"].replace("http://", "https://")

                # Need to do some imgur API nonsense to get all the direct image links out of galleries
                if (
                    "imgur.com/a/" in modified_url
                    or "imgur.com/gallery/" in modified_url
                ):

                    # Hashtag in url breaks it, so don't take it
                    if "#" in modified_url:
                        album_id = modified_url[
                            modified_url.rfind("/") + 1 : modified_url.rfind("#")
                        ]
                    else:
                        album_id = modified_url[modified_url.rfind("/") + 1 :]

                    response = requests.get(
                        f"https://api.imgur.com/3/album/{album_id}/images",
                        headers={
                            "Authorization": f"Client-ID {credentials['imgur_client_id']}"
                        },
                    )

                    # Check if the request was successful
                    if response.status_code == 200:
                        # Parse the JSON response
                        data = response.json()

                        # print(album_id)

                        direct_links = []
                        # Extract direct links to images from the response
                        for image in data["data"]:
                            # print(image["link"])
                            try:
                                direct_links.append(image["link"])
                            except TypeError as e:
                                continue

                        for link in direct_links:
                            # print(link)
                            child = [
                                {
                                    "object": "block",
                                    "embed": {"url": link},
                                },
                            ]

                            body["children"].extend(child)

                    else:
                        # If image doesn't exist anymore, considering set_sent_to_notion(post) and break-ing, to keep dead links out of the database
                        # But they could be historically interesting/useful, so I'm not sure. Leaving it in for now.
                        print("Imgur Error:", response.status_code)
                        print(modified_url)
                else:

                    image_id = modified_url[
                        modified_url.rfind("/") + 1 : modified_url.rfind(".")
                    ]
                    # print(image_id)

                    response = requests.get(
                        f"https://api.imgur.com/3/image/{image_id}",
                        headers={
                            "Authorization": f"Client-ID {credentials['imgur_client_id']}"
                        },
                    )

                    # Check if the request was successful
                    if response.status_code == 200:
                        # Parse the JSON response

                        # print("IMGUR SINGLE IMAGE", response.text)

                        child = [
                            {
                                "object": "block",
                                "embed": {"url": response.json()["data"]["link"]},
                            },
                        ]

                        body["children"].extend(child)

                    else:
                        # If image doesn't exist anymore, considering set_sent_to_notion(post) and break-ing, to keep dead links out of the database
                        # But they could be historically interesting/useful, so I'm not sure. Leaving it in for now.
                        print("Imgur Error:", response.status_code)
                        print(modified_url, response.text)

            # There's a third condition where the link goes somewhere else like Patreon but an image is embedded in the post - figure it out
            # Condition 5 - post removed from imgur (removed.png) or 404 (not sure why one happens over the other when they both have the same effect)
            # Condition 6 - x-post subreddit
            # If none of the above set sent_to_notion so it doesn't try again, and skip the actual send
            else:
                set_sent_to_notion(post, subreddit=subreddit)

                print(
                    f"{post['title']} is not a map or has no images attached, skipping..."
                )
                break

            # Embeds for Reddit don't work via Notion API due to an issue with iframely, using bookmarks instead:
            # https://developers.notion.com/changelog/users-can-now-add-equation-blocks-and-media-blocks
            child = [
                {
                    "object": "block",
                    "type": "bookmark",
                    "bookmark": {
                        # "caption": [
                        #     {
                        #         "type": "text",
                        #         "text": {"content": str(post["comments"])},
                        #     }
                        # ],
                        "url": "https://www.reddit.com"
                        + post["permalink"],
                    },
                }
            ]

            body["children"].extend(child)

            body = json.dumps(body)

            # print(body)

            notion_url = f"https://api.notion.com/v1/pages"

            response = requests.post(notion_url, data=body, headers=headers)
            # set_sent_to_notion(post)
            if response.status_code == 200:
                print(f"{post['title']} sent to Notion...")
                set_sent_to_notion(post, subreddit=subreddit)

                break
            else:
                print(
                    f"{post['title']} - {response.status_code} - {response.text} - Failed to send to Notion..."
                )
                break
            # Else repeat the loop - Notion is randomly dropping requests (rate limit?) so this will try again till it accepts it
            # Nah you know what that is, that's the non-maps we're not sending to Notion
            # Eh bad idea to loop on unknown error

        except httpx.RemoteProtocolError as e:
            time.sleep(5)


def handle_duplicates(
    post,
    overwrite,
    subreddit=None,
    notion_map_database=None,
    notion_titles_list=None,
    credentials=CREDENTIALS_FILE,
):

    if not subreddit:
        subreddit = post["subreddit"]

    # Needed to check if sent_to_notion exists

    ############## Gonna need this again soon

    # post_df = get_post_from_db(post)

    # print(type(post["sent_to_notion"]))
    # print(post["sent_to_notion"])

    if post["sent_to_notion"] == True and overwrite == False:
        print(f"{post['title']} already tagged sent_to_notion, skipping...")
        return False
    elif post["sent_to_notion"] == True and overwrite == True:
        print(f"{post['title']} already tagged sent_to_notion, overwriting...")

        with open(credentials) as credentials_json:
            credentials = json.load(credentials_json)

        token = credentials["notion_token"]

        headers = {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }

        notion_search_url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
        search_payload = {
            "filter": {"property": "Name", "title": {"equals": post["title"]}}
        }

        search_response = requests.post(
            notion_search_url, json=search_payload, headers=headers
        )

        print(search_response.json())

        for page in search_response.json()["results"]:
            notion_page_url = f"https://api.notion.com/v1/pages/{page['id']}"

            update_payload = {"archived": True}
            print(f"Duplicate page found for {post['title']}, deleting...")

            update_response = requests.patch(
                notion_page_url, json=update_payload, headers=headers
            )

        set_sent_to_notion(post, False, subreddit=subreddit)

        # sys.exit()
        # After deleting the page, set sent_to_notion to False, it will be set True again when it's sent back
        set_sent_to_notion(post, False, subreddit=subreddit)
        return True
    else:
        print(f"{post['title']} not tagged sent_to_notion, proceeding...")
        return True

    ##############

    # if not notion_map_database:
    # notion_map_database = get_notion_db_state()
    # notion_titles_list = [
    #     page["properties"]["Name"]["title"][0]["text"]["content"]
    #     for page in notion_map_database
    # ]

    # print(map_database)

    # with open(credentials) as credentials_json:
    #     credentials = json.load(credentials_json)

    # token = credentials["notion_token"]

    # Check that we're not inserting a duplicate - if the Title exists, delete (archive) all duplicates so we can make a new one
    # for page in notion_map_database:
    #     if post["title"] == page["properties"]["Name"]["title"][0]["text"]["content"]:

    # print(len(notion_titles_list))
    # if post["title"] in notion_titles_list:
    #     for page in notion_map_database:
    #         if (
    #             post["title"]
    #             == page["properties"]["Name"]["title"][0]["text"]["content"]
    #         ):
    #             page_id = page["id"]
    #             headers = {
    #                 "Authorization": "Bearer " + token,
    #                 "Content-Type": "application/json",
    #                 "Notion-Version": "2022-06-28",
    #             }

    #             notion_url = f"https://api.notion.com/v1/pages/{page_id}"

    #             update_payload = {"archived": True}

    #             if overwrite == True:
    #                 print(f"Duplicate page found for {post['title']}, deleting...")
    #                 res = requests.patch(
    #                     notion_url, json=update_payload, headers=headers
    #                 )
    #                 # print(page_id, res.json())
    #                 set_sent_to_notion(post, False)
    #             else:
    #                 print(f"Duplicate page found for {post['title']}, skipping...")
    #                 # set_sent_to_notion(post)
    #                 return False  # If not overwriting just break out of the function - nothing to do here.

    # print(len(notion_map_database))
    # print(f"{post['title']} not found in Notion, proceeding...")
    # return True


def get_notion_db_state(database_id=NOTION_DB_ID, credentials=CREDENTIALS_FILE):

    with open(credentials) as credentials_json:
        credentials = json.load(credentials_json)

    token = credentials["notion_token"]

    print(f"Getting state for Notion database {database_id}...")
    stop_event = threading.Event()
    timer_thread = threading.Thread(target=timer, args=(stop_event,))
    timer_thread.start()

    notion_client = Client(auth=token, timeout_ms=300000)

    try:
        notion_map_database = collect_paginated_api(
            notion_client.databases.query, database_id=database_id
        )
    except Exception as e:
        print("Error getting Notion DB state:", e)

    stop_event.set()
    timer_thread.join()
    return notion_map_database


def get_notion_db_state_2(database_id=NOTION_DB_ID, credentials=CREDENTIALS_FILE):

    with open(credentials) as credentials_json:
        credentials = json.load(credentials_json)

    token = credentials["notion_token"]

    print(f"Getting state for Notion database {database_id}...")
    stop_event = threading.Event()
    timer_thread = threading.Thread(target=timer, args=(stop_event,))
    timer_thread.start()

    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    notion_url = f"https://api.notion.com/v1/databases/{database_id}/query"

    # payload = {"page_size": 100}

    response = requests.post(notion_url, headers=headers)

    if response.status_code == 200:
        notion_map_database = response.json()

        print(notion_map_database)

        stop_event.set()
        timer_thread.join()
        return notion_map_database["results"]
    else:
        print("Error getting Notion DB state:", response.status_code, response.text)
        stop_event.set()
        timer_thread.join()


def get_notion_db_state_generator(
    database_id=NOTION_DB_ID, credentials=CREDENTIALS_FILE
):
    with open(credentials) as credentials_json:
        credentials = json.load(credentials_json)

    token = credentials["notion_token"]

    print(f"Getting API generator for Notion database {database_id}...")

    notion_client = Client(auth=token, timeout_ms=300000)

    return iterate_paginated_api(notion_client.databases.query, database_id=database_id)


def timer(stop_event):
    seconds = 0
    while not stop_event.is_set():
        print("\rTimer:", seconds, "seconds", end="", flush=True)
        seconds += 1
        time.sleep(1)


def build_notion_titles_list(
    notion_map_database_generator, notion_map_database, notion_titles_list
):
    count = 0
    for page in notion_map_database_generator:
        # print(page["properties"]["Name"]["title"][0]["text"]["content"])
        notion_titles_list.append(
            page["properties"]["Name"]["title"][0]["text"]["content"]
        )
        notion_map_database.append(page)

        count += 1
        if count % 100 == 0:
            print("Fetching Notion database from API...", len(notion_titles_list))

    return notion_titles_list


"""

    # Check that we're not inserting a duplicate - if the Title exists, delete (archive) all duplicates so we can make a new one
    if map_database["results"] != []:
        for page in map_database["results"]:
            # print(page)
            page_id = page["id"]

            headers = {
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            }

            notion_url = f"https://api.notion.com/v1/pages/{page_id}"

            update_payload = {"archived": True}

            if overwrite == True:

                res = requests.patch(notion_url, json=update_payload, headers=headers)

                # print(page_id, res.json())
                print("Duplicate page found, deleting...")
                print(embed_url + urllib.parse.quote(thumbnail))
                print(page_id)
            else:
                print("Duplicate page found, skipping...")
                print(embed_url + urllib.parse.quote(thumbnail))
                return  # If not overwriting just break out of the function - nothing to do here.

    new_page = {
        "Name": {"title": [{"text": {"content": title}}]},
        "Tags": {"type": "multi_select", "multi_select": tags},
    }

    page_response = notion.pages.create(
        parent={"database_id": NOTION_DB_ID}, properties=new_page
    )

    # print("PAGE_RESPONSE:", page_response, "\n\n\n\n")

    page_id = page_response["id"]

    notion.blocks.children.append(
        block_id=page_id,
        children=[
            {
                "object": "block",
                "embed": {"url": embed_url + urllib.parse.quote(thumbnail)},
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {"content": f"Variants: {variants}"},
                        }
                    ]
                },
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": f"{url + urllib.parse.quote(path)}",
                                "link": {"url": f"{url + urllib.parse.quote(path)}"},
                            },
                        }
                    ]
                },
            },
        ],
    )

    print(f"Sent {title} to Notion")
    # print(map_database, "\n")
"""
