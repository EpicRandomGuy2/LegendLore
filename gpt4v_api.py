import os
import sys
import time
import base64
import requests
import re
import itertools
import traceback
import urllib.parse
import httpx
import json
import copy
import backoff
import mongodb_local
import openai
from bs4 import BeautifulSoup
from openai import OpenAI
from pandas import DataFrame
from config import CONNECTION_STRING, DB_NAME, DEFAULT_SUBREDDIT, TAGS, CREDENTIALS_FILE


def is_tagged_gpt4v(post):

    return "GPT-4V" in str(post["tags"])


def is_tagged_untagged(post):

    return "Untagged" in str(post["tags"])


def get_first_image(post, credentials=CREDENTIALS_FILE):
    with open(credentials) as credentials_json:
        credentials = json.load(credentials_json)

    # LegendLore only passes the first image in a post to GPT to keep costs lower
    # Currently handles Reddit and Imgur posts well, but there's a lot of variation in those urls
    # Inkarnate was not super feasible due to needing JS to retrieve a direct link to the image

    # Basic and most common case, just return the image link as long as it doesn't resolve to 404
    if "i.redd.it" in post["url"]:
        response = requests.head(post["url"], allow_redirects=True)
        if response.status_code == 200:
            return post["url"]
        else:
            print(
                f"{post['title']} - {post['url']} - {response.status_code}, skipping..."
            )
            return None

    # Second most common case, return the first post in a Reddit gallery
    elif "reddit.com/gallery" in post["url"]:
        # https://www.reddit.com/r/redditdev/comments/paia21/how_to_get_image_url_using_praw_instead_of_the/
        try:
            # Many of these gallery images return a 404, send the first 200 to GPT.
            for image in post["media_metadata"].values():
                # This is just how the keys come back from the Reddit API
                image = image["s"]["u"]
                response = requests.head(image, allow_redirects=True)
                if response.status_code == 200:
                    # print(image, response.status_code)
                    return image
                else:
                    # print(image, response.status_code)
                    continue

            # If it goes through the whole gallery without hitting a valid image, don't send it to GPT.
            print(
                f"{post['title']} - {post['media_metadata']} - {response.status_code}, skipping..."
            )
            return None

        # Rarely media_metadata is a float for some reason?? Or just missing.
        except (AttributeError, KeyError) as e:
            print(f"{e}: https://www.reddit.com{post['permalink']}")
            return None

    # Very rare case from like pre-2013: Just return the url
    elif "reddituploads" in post["url"]:
        return post["url"]

    # The other most common case - imgur albums /a/ , /gallery/ - Get the first image from an imgur gallery
    # Direct links are easier
    # Some extra work in the Imgur API is needed to ensure a valid direct image link
    elif "imgur.com" in post["url"]:

        # Change all http links to https or Imgur 404s
        modified_url = (
            post["url"]
            .strip("/")
            .strip("/new")
            .strip("/all")
            .replace("http://", "https://")
        )

        # Need to do some imgur API nonsense to get all the direct image links out of galleries
        if "imgur.com/a/" in modified_url or "imgur.com/gallery/" in modified_url:

            # Hashtag in url breaks it, so drop it and everything after (link still works without it)
            if "#" in modified_url:
                album_id = modified_url[
                    modified_url.rfind("/") + 1 : modified_url.rfind("#")
                ]
            else:
                album_id = modified_url[modified_url.rfind("/") + 1 :]

            # Hit Imgur API so we can get some direct image links
            response = requests.get(
                f"https://api.imgur.com/3/album/{album_id}/images",
                headers={
                    "Authorization": f"Client-ID {credentials['imgur_client_id']}"
                },
            )

            # Return image if valid
            if response.status_code == 200:
                data = response.json()
                return data["data"][0]["link"]

            else:
                # If image doesn't exist anymore, considering set_sent_to_notion(post) and break-ing, to keep dead links out of the database
                # But they could be historically interesting/useful, so I'm not sure. Leaving it in for now.
                print("Imgur Error:", response.status_code)
                print(modified_url)
                return 404

        # Direct link handling
        else:

            # Hashtag in url breaks it, so drop it and everything after (link still works without it)
            if "#" in modified_url:
                modified_url = modified_url[: modified_url.rfind("#")]

            image_id = modified_url[
                modified_url.rfind("/") + 1 : modified_url.rfind(".")
            ]

            # print(image_id)

            # Edge case: If the first one failed because there's no extension, just take the end of the url
            if image_id == "":
                image_id = modified_url[modified_url.rfind("/") + 1 :]
                # print(image_id)

            # Hit Imgur API so we can get some direct image links
            response = requests.get(
                f"https://api.imgur.com/3/image/{image_id}",
                headers={
                    "Authorization": f"Client-ID {credentials['imgur_client_id']}"
                },
            )

            # Return image if valid
            if response.status_code == 200:
                # print("IMGUR SINGLE IMAGE", response.text)
                return response.json()["data"]["link"]

            else:
                # If image doesn't exist anymore, considering set_sent_to_notion(post) and break-ing, to keep dead links out of the database
                # But they could be historically interesting/useful, so I'm not sure. Leaving it in for now.
                print("Imgur Error:", response.status_code)
                print(modified_url)  # , response.text)
                return 404

    # Don't pass non-Reddit or non-Imgur links to GPT (saves money)
    else:
        return None


# Backoff behavior
def giveup(details):
    print("Max number of tries succeeded, giving up...")
    print(details)
    sys.exit()


# Backoff for GPT rate limiting
@backoff.on_exception(
    backoff.expo, openai.RateLimitError, max_tries=3, on_giveup=giveup
)
def gpt4v_analyze_image(post, resolution="low", credentials=CREDENTIALS_FILE):
    # This function works by taking a list of tags from config.py and asking GPT-Vision to tag the image
    # Sometimes it talks a bit too much, so we filter out any word from the response that isn't in the TAGS list
    tags = []

    valid_tags = TAGS

    with open(credentials) as credentials_json:
        credentials = json.load(credentials_json)

    api_key = credentials["openai_api_key"]

    # This prompt seems to be a good balance of cost (tokens)/tagging accuracy
    # Most cost (tokens) comes from the image analysis and response regardless
    prompt = f"Analyze this D&D top-down map titled '{post['title']}'. In your response, only list prominently featured terms from this list with commas, no spaces: {valid_tags}"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    # Get the URL to pass to GPT
    first_image = get_first_image(post)

    # If a post errored or is not an image, don't waste the GPT call
    if first_image == None:
        tags.append({"name": "Untagged"})
        tags.append({"name": "GPT-4V"})
        return tags
    # Skip if 404
    elif first_image == 404:
        print(f"{post['title']} 404, skipping...")
        tags.append({"name": "Untagged"})
        tags.append({"name": "404"})
        tags.append({"name": "GPT-4V"})
        return tags
    # Skip if over 20MB, GPT can't handle it
    # This annoyingly doesn't work half the time, not sure why - might need to lower the number
    elif len(requests.get(first_image).content) >= 20971520:
        print("Image is too large for GPT, skipping...")
        tags.append({"name": "Untagged"})
        tags.append({"name": "GPT-4V"})
        return tags
    else:

        payload = {
            "model": "gpt-4o",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": first_image,
                                "detail": resolution,  # Really need this to be low, but it's not working on a subset of images (~10k or so) that may need high to even recognize it received an image
                                # To do: If vague error on image, try again on auto. Increases the API cost a ton. Expected additional monthly cost from autos: $1.66
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 300,
        }

        response = requests.post(
            "https://api.openai.com/v1/chat/completions", headers=headers, json=payload
        )

        print("Sent to GPT:", first_image)

        print(response.json(), "\n")

        # If GPT responded nicely, process the tags
        if not response.json().get("error"):

            tags_response = response.json()["choices"][0]["message"]["content"]

            print("GPT responded with tags:", tags_response, "\n")

            # Split by anything that is not a word/number/underscore/dash/slash
            tags_response = re.split("[^a-zA-Z0-9_\-\/]", tags_response)

            print("Pre-Processed Tags:", tags_response, "\n")

            # Need to do some processing on the tags
            processed_tags = []

            for tag in tags_response:
                if tag in valid_tags:
                    tag = tag.replace("_", " ")  # Normalize tag name
                    processed_tags.append({"name": tag})  # Notion wants this format
                else:
                    # Just a funny artifact from the split where it would acquire a couple "" somehow
                    # Bad regex I guess
                    if tag != "":
                        # print("Invalid Tag:", tag, "-- Discarding...", "\n")
                        pass

            # Sort tags in name order so it looks cleaner in MongoDB and Notion later
            processed_tags = sorted(processed_tags, key=lambda x: x["name"])

            # If processed_tags was empty, likely because GPT said this isn't a map, add Untagged to it and continue
            if processed_tags == tags:
                processed_tags.append({"name": "Untagged"})

            # This goes on the end of the list for cleanliness in the Notion UI
            # Actually this doesn't go to Notion anymore but may be needed later
            # (e.g. if I manually upload maps and need to make the distinction, etc.)
            processed_tags.append({"name": "GPT-4V"})

            print("Processed Tags:", processed_tags, "\n")

            return processed_tags

        # Handling the many common GPT error responses
        elif (
            "unsupported image" in response.json().get("error").get("message")
            or "Invalid image" in response.json().get("error").get("message")
            or "error processing" in response.json().get("error").get("message")
        ):
            try:
                # Tell me what image and why
                print(first_image)
                print(response.json().get("error").get("message"))
                tags.append({"name": "Untagged"})
                tags.append({"name": "GPT-4V"})
                return tags
            # Sometimes it's not a proper "error", just GPT flipping out in the response
            # cause the image isn't big enough to analyze, or some other vague reason it won't disclose
            except Exception:
                # Inform me and keep going
                print(traceback.format_exc())
                tags.append({"name": "Untagged"})
                tags.append({"name": "GPT-4V"})
                return tags
        else:
            print(response.json().get("error").get("message"))
            tags.append({"name": "Untagged"})
            tags.append({"name": "GPT-4V"})
            return tags


def analyze_and_tag_post(post, append=False, subreddit=DEFAULT_SUBREDDIT):
    # Analyze untagged posts only - you can set append to True but it's not worth
    # to update the tags ($$$)
    # Updates both sub-specific and "all" databases
    if not is_tagged_gpt4v(post) or append == True:
        tags = gpt4v_analyze_image(post, resolution="low")
        mongodb_local.add_tags_to_post(post, tags, subreddit=post["subreddit"])
        mongodb_local.add_tags_to_post(post, tags, subreddit="all")
    else:
        print(f"{post['title']} is already tagged, skipping tags...")


def analyze_untagged_post(post, append=False, subreddit=DEFAULT_SUBREDDIT):
    # If post is tagged as Untagged due to some earlier failure or skip, try again, remove the Untagged tag before tagging.
    # Also check to see if it's been sent to Notion already - if it has, skip it, can't afford to be updating old tags ($$$)
    if is_tagged_untagged(post) and post["sent_to_notion"] == False:
        print(f"{post['title']} is tagged Untagged, doing second pass...")
        tags = gpt4v_analyze_image(post, resolution="auto")
        mongodb_local.reset_post_tags(
            post, subreddit=post["subreddit"], confirm_all=True
        )
        mongodb_local.add_tags_to_post(post, tags, subreddit=post["subreddit"])
        mongodb_local.reset_post_tags(post, subreddit="all", confirm_all=True)
        mongodb_local.add_tags_to_post(post, tags, subreddit="all")
