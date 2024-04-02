import zstandard
import json
import sys
import io

# This script deals with pushshift zst data, was used to build out LegendLore on posts > 1000 posts ago (Reddit API's limit)
# Builds a big, proper json file out of every year/month's data - it switched from yearly to monthly at some point, ugh
# Honestly don't use this for anything it's terrible

# print(json.load(open("./pushshift/json/test_submissions.json", "r")))

for i in range(1, 2):

    if i <= 9:
        filename = f"RS_2024-0{i}"
    elif i >= 10:
        filename = f"RS_2024-{i}"

    subreddits = [
        "battlemaps",
        "dndmaps",
        "dungeondraft",
        "FantasyMaps",
        "inkarnate",
    ]

    # The part we need to make jsons

    zst_string = ""

    with open(f"./pushshift/zst/{filename}.zst", "rb") as file_zst:

        zst = zstandard.ZstdDecompressor(max_window_size=2147483648)
        reader = zst.stream_reader(file_zst)

        text_stream = io.TextIOWrapper(reader, encoding="utf-8")

        # filtered_zst_json = {
        #     "battlemaps": [],
        #     "dndmaps": [],
        #     "dungeondraft": [],
        #     "FantasyMaps": [],
        #     "inkarnate": [],
        # }

        for line in text_stream:
            submission = json.loads(line)
            subreddit = submission["subreddit"]
            if subreddit in subreddits:
                with open(
                    f"./pushshift/json/{filename}_{subreddit}.json", "a"
                ) as file_json:
                    # filtered_zst_json[subreddit].append(submission)
                    print(submission["title"])
                    submission = json.dumps(submission)
                    file_json.write(submission + "\n")

    for subreddit in subreddits:
        try:
            new_json = {"submissions": []}

            with open(
                f"./pushshift/json/{filename}_{subreddit}.json", "r"
            ) as file_json:
                for line in file_json:
                    print(line)
                    new_json["submissions"].append(json.loads(line.strip()))

                with open(
                    f"./pushshift/json/{filename}_{subreddit}_final.json", "w"
                ) as file_json_final:
                    file_json_final.write(json.dumps(new_json))
        except FileNotFoundError as e:
            continue
