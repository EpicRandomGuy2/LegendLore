import time
import re
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
from config import NOTION_DB_ID, CREDENTIALS_FILE, IGNORE_SENT_TO_NOTION
from do_not_post import DO_NOT_POST
from name_change import NAME_CHANGE
from pprint import pprint


def send_to_notion(
    post,
    overwrite=False,
    ignore_sent_to_notion=IGNORE_SENT_TO_NOTION,
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
    # If the creator has requested to be excluded from LegendLore, return without posting
    # set sent_to_notion flag so it won't attempt again in the future
    elif name_in_do_not_post(post):
        print(f"{post['title']} - {post['author']} in do_not_post, skipping...")
        set_sent_to_notion(post, subreddit=subreddit)
        return

    # If dupe and no overwrite, skip this post
    elif (
        handle_duplicates(
            post,
            overwrite,
            ignore_sent_to_notion=ignore_sent_to_notion,
            subreddit=subreddit,
        )
        == False
    ):
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
                    "Link": {"url": get_creator_link(post)},
                    "Score": {"type": "number", "number": post["score"]},
                    "Subreddit": {
                        "type": "multi_select",
                        "multi_select": [{"name": f"r/{post['subreddit']}"}],
                    },
                    "Date": {"date": {"start": post["created_time"]}},
                },
                "children": [],
            }

            # If map is tagged [AI] in title, set sent_to_notion so it doesn't try again, and skip the actual send
            if "[AI]" in post["title"].upper():
                set_sent_to_notion(post, subreddit=subreddit)

                print(f"{post['title']} is tagged [AI], skipping...")
                break
            # Create children for each post - the embed and Reddit link
            # Different urls need to have embedding handled differently
            elif "i.redd.it" in post["url"]:
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

            # Append first comment child if it exists, else skip and move on
            try:
                first_comment = post["comments"][0]

                # API only accepts 2000 characters per block - need to break it up
                number_of_blocks = (len(first_comment) // 2000) + 1
                word_break_index = 0
                new_block_first_word = ""

                for i in range(0, number_of_blocks):

                    # Logic to stop blocks from splitting words down the middle
                    word_block = first_comment[2000 * i : 2000 * (i + 1)]

                    # On the last loop we need the last word, there will be no rightmost_space
                    # so set it to take the highest possible index
                    if i != number_of_blocks - 1:
                        rightmost_space = word_block.rfind(" ")

                    else:
                        # Stops the last part of the post from getting cut off due to no space
                        rightmost_space = 2000

                    word_break_index = 2000 * i + rightmost_space

                    child = [
                        {
                            "object": "block",
                            "type": "quote",
                            "quote": {
                                "rich_text": parse_markdown_links(
                                    new_block_first_word
                                    + first_comment[2000 * i : word_break_index]
                                )
                            },
                        }
                    ]

                    # Don't include the space in the new block
                    new_block_first_word = word_block[rightmost_space + 1 :]

                    # print(child)

                    body["children"].extend(child)
            except IndexError as e:
                pass

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
    ignore_sent_to_notion=IGNORE_SENT_TO_NOTION,
    subreddit=None,
    credentials=CREDENTIALS_FILE,
):

    # If rebuilding the whole database, no need for dupe handling (this speeds things up a ton)
    if ignore_sent_to_notion:
        return True

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


def name_in_do_not_post(post):

    return post["author"] in DO_NOT_POST


# Need a parser because Notion is wack and doesn't natively do markdown. Only doing it for links for now.
def parse_markdown_links(text):
    pattern = r"\[([^\]]+)\]\((http[s]?://[^\)]+)\)|http[s]?://[\w./%?#=-]+"
    segments = []
    last_end = 0

    for match in re.finditer(pattern, text):
        start_text = text[last_end : match.start()]
        if start_text:
            # At the risk of chopping off a few letters, do not let this be longer than 2000 or Notion's API will error
            segments.append({"type": "text", "text": {"content": start_text[:2000]}})

        if match.group(1) and match.group(2):
            link_text = match.group(1)  # Link text
            link_url = match.group(2)  # URL
            segments.append(
                {
                    "type": "text",
                    "text": {"content": link_text, "link": {"url": link_url}},
                    "annotations": {"bold": True},
                }
            )
        else:
            link_url = match.group(0)  # The entire match is the URL
            segments.append(
                {
                    "type": "text",
                    "text": {"content": link_url, "link": {"url": link_url}},
                }
            )

        last_end = match.end()

    # Text after the last link (if any)
    remaining_text = text[last_end:]
    if remaining_text:
        # At the risk of chopping off a few letters, do not let this be longer than 2000 or Notion's API will error
        segments.append({"type": "text", "text": {"content": remaining_text[:2000]}})

    return segments


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


def send_updated_username_to_notion(name, posts, credentials=CREDENTIALS_FILE):

    print(f"Updating names for {name} -> {NAME_CHANGE[name]} in Notion...")

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
        "filter": {
            "property": "Creator",
            "title": {"equals": name},
        }
    }

    search_response = requests.post(
        notion_search_url, json=search_payload, headers=headers
    )

    # print(search_response.json())

    # Update score for all pages matching post title
    count = 1
    for page in search_response.json()["results"]:

        notion_page_url = f"https://api.notion.com/v1/pages/{page['id']}"

        update_payload = {
            "properties": {
                "Creator": {
                    "type": "rich_text",
                    "rich_text": [{"text": {"content": NAME_CHANGE[name]}}],
                },
            }
        }
        
        update_response = requests.patch(
            notion_page_url, json=update_payload, headers=headers
        )

        # print(update_response.json())

        print(count)
        count += 1

    incorrect_updated_username_hotfix(name, posts)


def get_creator_link(post, credentials=CREDENTIALS_FILE):
    # Returns None if no url (empty string throws an API error)
    creator_link = None

    # If there is a comment
    if len(post["comments"]) > 0:
        # Url regex
        pattern = r"http[s]?://(?:[a-zA-Z]|[0-9]|[_#?./%=-])+"

        urls = re.findall(pattern, post["comments"][0])

        # Get the first Patreon link - Doing a loop to check for Patreon links first
        # to set them as higher priority (if it goes in order it might grab a wikipedia link or something)
        for url in urls:
            if "patreon" in url:
                creator_link = url
                return creator_link

        # If no Patreon link just get the first other non-imgur non-reddit link
        # (right 99% of the time, sometimes it grabs silly links like wikipedia)
        for url in urls:
            if not "imgur" in url and not "reddit" in url:
                creator_link = url
                return creator_link

    # If no url return None
    return creator_link


def incorrect_updated_username_hotfix(name, posts, credentials=CREDENTIALS_FILE):

    print(f"Fixing names for {NAME_CHANGE[name]} in Notion...")

    with open(credentials) as credentials_json:
        credentials = json.load(credentials_json)

    token = credentials["notion_token"]

    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    # Get all pages with incorrectly updated names
    notion_search_url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    search_payload = {
        "filter": {
            "property": "Creator",
            "title": {"equals": NAME_CHANGE[name]},
        }
    }

    search_response = requests.post(
        notion_search_url, json=search_payload, headers=headers
    )

    # print(search_response.json())

    # Revert all those pages back to their original names from MongoDB
    count = 1
    for page in search_response.json()["results"]:

        notion_title = page["properties"]["Name"]["title"][0]["text"]["content"]

        post = get_post_from_db(notion_title).iloc[0].to_dict()

        db_author = post["author"].lstrip("u/")

        notion_creator = page["properties"]["Creator"]["rich_text"][0]["text"][
            "content"
        ]

        # If there's both a Notion page mismatch and DB mismatch
        if db_author != notion_creator and db_author != name:
            print(f"Correcting {notion_creator} to {db_author} on {notion_title}...")
            corrected_name = db_author
        else:
            continue

        notion_page_url = f"https://api.notion.com/v1/pages/{page['id']}"

        update_payload = {
            "properties": {
                "Creator": {
                    "type": "rich_text",
                    "rich_text": [{"text": {"content": corrected_name}}],
                },
            }
        }

        update_response = requests.patch(
            notion_page_url, json=update_payload, headers=headers
        )

        print(count)
        count += 1


# Untested, unused function - for updating links on existing pages only
# def send_creator_link_to_notion(post, credentials=CREDENTIALS_FILE):

#     print(f"Adding Patreon link for {post['author']} in Notion...")

#     with open(credentials) as credentials_json:
#         credentials = json.load(credentials_json)

#     token = credentials["notion_token"]

#     headers = {
#         "Authorization": "Bearer " + token,
#         "Content-Type": "application/json",
#         "Notion-Version": "2022-06-28",
#     }

#     # Get page by title
#     notion_search_url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
#     search_payload = {
#         "filter": {"property": "Name", "title": {"equals": post["title"]}}
#     }

#     search_response = requests.post(
#         notion_search_url, json=search_payload, headers=headers
#     )

#     # print(search_response.json())

#     # Update score for all pages matching post title
#     for page in search_response.json()["results"]:

#         notion_page_url = f"https://api.notion.com/v1/pages/{page['id']}"

#         # Returns None if no url (empty string throws an API error)
#         creator_link = None

#         try:
#             # Url regex
#             pattern = r"http[s]?://(?:[a-zA-Z]|[0-9]|[_#?./%=-])+"

#             urls = re.findall(pattern, post["comments"][0])

#             Get the first Patreon link - Doing a loop to check for Patreon links first
#             to set them as higher priority (if it goes in order it might grab a wikipedia link or something)
#             for url in urls:
#                 if "patreon" in url:
#                     creator_link = url
#                     return creator_link

#             # Get the first Patreon link
#             for url in urls:
#                 # Filter out Imgur and Reddit cause they're usually not going to a creator's site
#                 if not "imgur" in url and not "reddit" in url:
#                     creator_link = url
#                     break

#             update_payload = {
#                 "properties": {
#                     "Creator": {"url": creator_link},
#                 },
#             }

#             update_response = requests.patch(
#                 notion_page_url, json=update_payload, headers=headers
#             )

#         except IndexError as e:
#             print(post["title"], "error adding creator_link:", e)

#         # print(update_response.json())
