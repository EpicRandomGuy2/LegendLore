import time
import requests
import json
import httpx
import time
from notion_client import Client
from notion_client.helpers import collect_paginated_api
from notion_client.helpers import iterate_paginated_api
from openai import OpenAI
from bs4 import BeautifulSoup
from mongodb_local import get_database_client, get_post_from_db, set_sent_to_notion
from pandas import DataFrame
from config import NOTION_DB_ID, CREDENTIALS_FILE
from pprint import pprint


def send_to_notion(
    post,
    overwrite=False,
    update_score=False,
    updated_score_titles=set(),
    subreddit=None,
    credentials=CREDENTIALS_FILE,
):
    if not subreddit:
        subreddit = post["subreddit"]

    # https://developers.notion.com/reference/post-page

    # If a post exists in Notion already and needs its score updated, do it and exit
    if (
        update_score == True
        and post["sent_to_notion"] == True
        and post["title"] in updated_score_titles
    ):
        send_updated_score_to_notion(
            post, subreddit=subreddit, credentials=CREDENTIALS_FILE
        )
        return

    # If dupe and no overwrite, skip this post
    elif handle_duplicates(post, overwrite, subreddit=subreddit) == False:
        return
    # Else if post does not exist, or if we are overwriting, make post as usual

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

            # If it's a regional map, drop the other tags because they are very cluttery
            # For Town/City, it sometimes tagged very gratuitously on something that should
            # have honestly been regional, so correct that here. Arbitrarily picked 8+, saw
            # some normal battlemaps with 8.
            # This screws some of the posts but seems to mostly be accurate
            if "Regional/World" in str(post["tags"]):
                tags = [{"name": "Regional/World"}]
            elif "Town/City" in str(post["tags"]) and len(post["tags"]) >= 8:
                tags = [{"name": "Regional/World"}]

            # Create the attributes for each post
            body = {
                "parent": {"database_id": NOTION_DB_ID},
                "properties": {
                    "Name": {"title": [{"text": {"content": post["title"]}}]},
                    "Tags": {"type": "multi_select", "multi_select": tags},
                    # Once upon a time I tried to make Creator multi-select, it slowed the database
                    # so badly I couldn't even delete it correctly. It's prettier but not worth at scale.
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

            # Create children for each post - the embed and Reddit link

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

                    if response.status_code == 200:
                        data = response.json()

                        # print(album_id)

                        direct_links = []
                        # Extract direct links to images from the response
                        for image in data["data"]:
                            # print(image["link"])
                            try:
                                direct_links.append(image["link"])
                            # Skip if error
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

                    # Hashtag in url breaks it, so don't take it
                    if "#" in modified_url:
                        modified_url = modified_url[: modified_url.rfind("#")]

                    image_id = modified_url[
                        modified_url.rfind("/") + 1 : modified_url.rfind(".")
                    ]
                    print(image_id)

                    # If the first one failed because there's no extension, just take the end of the url
                    if image_id == "":
                        image_id = modified_url[modified_url.rfind("/") + 1 :]
                        print(image_id)

                    response = requests.get(
                        f"https://api.imgur.com/3/image/{image_id}",
                        headers={
                            "Authorization": f"Client-ID {credentials['imgur_client_id']}"
                        },
                    )
                    if response.status_code == 200:

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

            # To-do:
            # There's a third condition where the link goes somewhere else like Patreon but an image is embedded in the post - figure it out
            # Condition 6 - x-post subreddit
            # Condition 7: Inkarnate.com

            # If none of the above set sent_to_notion so it doesn't try again, and skip the actual send
            else:
                set_sent_to_notion(post, subreddit=subreddit)

                print(
                    f"{post['title']} is not a map or has no images attached, skipping..."
                )
                break

            # Embeds for Reddit don't work via Notion API due to an issue with iframely, using bookmarks instead:
            # https://developers.notion.com/changelog/users-can-now-add-equation-blocks-and-media-blocks
            # If you know how to get Reddit embeds working pleaaaaaase hit me up
            child = [
                {
                    "object": "block",
                    "type": "bookmark",
                    "bookmark": {
                        "url": "https://www.reddit.com" + post["permalink"],
                    },
                }
            ]

            body["children"].extend(child)

            body = json.dumps(body)

            # print(body)

            notion_url = f"https://api.notion.com/v1/pages"

            response = requests.post(notion_url, data=body, headers=headers)

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
    credentials=CREDENTIALS_FILE,
):

    if not subreddit:
        subreddit = post["subreddit"]

    # If the post has been sent to Notion and we're not overwriting, just skip it

    if post["sent_to_notion"] == True and overwrite == False:
        print(f"{post['title']} already tagged sent_to_notion, skipping...")
        return False

    # If it has been sent and we ARE overwriting, need to delete the old post
    # so the parent function can send the new one
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

        # Search post by title, this can come up with multiple matches, it will delete them all
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

        # After deleting the page, set sent_to_notion to False, it will be set True again when it's sent back
        set_sent_to_notion(post, False, subreddit=subreddit)
        return True
    else:
        print(f"{post['title']} not tagged sent_to_notion, proceeding...")
        return True


def send_updated_score_to_notion(
    post,
    subreddit=None,
    credentials=CREDENTIALS_FILE,
):
    if not subreddit:
        subreddit = post["subreddit"]

    with open(credentials) as credentials_json:
        credentials = json.load(credentials_json)

    token = credentials["notion_token"]

    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    # Get page by title
    notion_search_url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    search_payload = {
        "filter": {"property": "Name", "title": {"equals": post["title"]}}
    }

    search_response = requests.post(
        notion_search_url, json=search_payload, headers=headers
    )

    # print(search_response.json())

    # Update score for all pages matching post title
    for page in search_response.json()["results"]:

        notion_page_url = f"https://api.notion.com/v1/pages/{page['id']}"

        update_payload = {"properties": {"Score": {"number": post["score"]}}}
        print(f"Updating score for {post['title']} in Notion...")

        update_response = requests.patch(
            notion_page_url, json=update_payload, headers=headers
        )

        # print(update_response.json())
