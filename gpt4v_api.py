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
from openai import OpenAI
from pandas import DataFrame
from config import CONNECTION_STRING, DB_NAME, DEFAULT_SUBREDDIT, TAGS, CREDENTIALS_FILE


def is_tagged_gpt4v(post):

    return "GPT-4V" in str(post["tags"])


def get_first_image(post, credentials=CREDENTIALS_FILE):
    with open(credentials) as credentials_json:
        credentials = json.load(credentials_json)

    if "i.redd.it" in post["url"]:
        response = requests.head(post["url"], allow_redirects=True)
        if response.status_code == 200:
            return post["url"]
        else:
            print(
                f"{post['title']} - {post['url']} - {response.status_code}, skipping..."
            )
            return None

    elif "reddit.com/gallery" in post["url"]:
        # https://www.reddit.com/r/redditdev/comments/paia21/how_to_get_image_url_using_praw_instead_of_the/
        try:
            # Many of these gallery images return a 404, send the first 200 to GPT.
            for image in post["media_metadata"].values():
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

    # Condition 4 - imgur albums /a/ , /gallery/ - This embeds in Notion but not API, may need to just get the first image, or all of them and embed them in sequence
    # Condition 4.5 - imgur embeds (non-gallery) randomly not working - fixed by getting direct link to image
    elif "imgur.com" in post["url"]:

        # Change all http links to https or Imgur 404s
        modified_url = post["url"].replace("http://", "https://")

        # Need to do some imgur API nonsense to get all the direct image links out of galleries
        if "imgur.com/a/" in modified_url or "imgur.com/gallery/" in modified_url:

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

                return data["data"][0]["link"]

            else:
                # If image doesn't exist anymore, considering set_sent_to_notion(post) and break-ing, to keep dead links out of the database
                # But they could be historically interesting/useful, so I'm not sure. Leaving it in for now.
                print("Imgur Error:", response.status_code)
                print(modified_url)

                return None
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

                return response.json()["data"]["link"]

            else:
                # If image doesn't exist anymore, considering set_sent_to_notion(post) and break-ing, to keep dead links out of the database
                # But they could be historically interesting/useful, so I'm not sure. Leaving it in for now.
                print("Imgur Error:", response.status_code)
                print(modified_url, response.text)
                return None
    else:
        return None


def giveup(details):
    print("Max number of tries succeeded, giving up...")
    print(details)
    sys.exit()


@backoff.on_exception(
    backoff.expo, openai.RateLimitError, max_tries=3, on_giveup=giveup
)
def gpt4v_analyze_image(post, credentials=CREDENTIALS_FILE):
    # To do: Mostly rip the above GPT4V API stuff to pass in a URL and get tags back. Return list of tags.
    tags = []

    valid_tags = TAGS

    with open(credentials) as credentials_json:
        credentials = json.load(credentials_json)

    api_key = credentials["openai_api_key"]

    # prompt = f"This is a Dungeons and Dragons top-down map. Title is {post['title']}. Provide a comma-separated list, no spaces, containing only exact terms from this list that are relevant to the image and title: {valid_tags}"
    prompt = f"Analyze a D&D top-down map titled '{post['title']}'. List prominently featured terms from this list with commas, no spaces: {valid_tags}"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    first_image = get_first_image(post)

    # If a post errored or is not an image, don't waste the GPT call
    if first_image == None:
        tags.append({"name": "Untagged"})
        tags.append({"name": "GPT-4V"})
        return tags
    else:
        payload = {
            "model": "gpt-4-vision-preview",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": first_image,
                                "detail": "low",
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

        # To do - Rate limit handling

        print(response.json(), "\n")

        if not response.json().get("error"):

            tags_response = response.json()["choices"][0]["message"]["content"]

            print("GPT responded with tags:", tags_response, "\n")

            # Start with the first tags defined at the top of the function
            processed_tags = []

            # tags_response = tags_response.replace(", ", ",")  # Allows spaces in tags but would ruin everything if GPT decided to respond in the wrong format even once. Underscores work and are better.
            tags_response = re.split("[^a-zA-Z0-9_\-\/]", tags_response)

            print("Pre-Processed Tags:", tags_response, "\n")

            for tag in tags_response:
                if tag in valid_tags:
                    tag = tag.replace("_", " ")  # Normalize tag name
                    processed_tags.append({"name": tag})
                else:
                    if tag != "":  # Just a funny artifact from the split
                        print("Invalid Tag:", tag, "-- Discarding...", "\n")

            processed_tags = sorted(processed_tags, key=lambda x: x["name"])

            # If processed_tags was empty, likely because GPT said this isn't a map, add Untagged to it and continue
            if processed_tags == tags:
                processed_tags.append({"name": "Untagged"})

            # This goes on the end of the list for cleanliness in the Notion UI
            processed_tags.append({"name": "GPT-4V"})

            print("Processed Tags:", processed_tags, "\n")

            return processed_tags

        elif (
            "unsupported image" in response.json().get("error").get("message")
            or "Invalid image" in response.json().get("error").get("message")
            or "error processing" in response.json().get("error").get("message")
        ):
            try:
                print(first_image)
                print(response.json().get("error").get("message"))
                tags.append({"name": "Untagged"})
                tags.append({"name": "GPT-4V"})
                return tags
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
    if not is_tagged_gpt4v(post) or append == True:
        tags = gpt4v_analyze_image(post)
        # mongodb_local.add_tags_to_post(post, tags, subreddit=subreddit)
        mongodb_local.add_tags_to_post(post, tags, subreddit=post["subreddit"])
        mongodb_local.add_tags_to_post(post, tags, subreddit="all")
    else:
        print(f"{post['title']} is already tagged, skipping tags...")

        # After testing, tags will be updated in both DBs
        # mongodb_local.add_tags_to_post(post, tags, subreddit=post["subreddit"])
        # mongodb_local.add_tags_to_post(post, tags, subreddit="all")
