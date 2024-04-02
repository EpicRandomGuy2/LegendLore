import zstandard
import json
import sys

# This script deals with pushshift zst data, was used to build out LegendLore on posts > 1000 posts ago (Reddit API's limit)
# Builds a big, proper json file out of every year/month's data - it switched from yearly to monthly at some point, ugh
# Honestly don't use this for anything it's terrible

# print(json.load(open("./pushshift/json/test_submissions.json", "r")))

subreddits = ["battlemaps", "dndmaps", "dungeondraft", "FantasyMaps", "inkarnate"]

# The part we need to make jsons

zst_string = ""

with open("./pushshift/zst/RS_2023-01.zst", "rb") as file_zst:

    zst = zstandard.ZstdDecompressor()
    reader = zst.stream_reader(file_zst)

    while True:
        chunk = reader.read(16384)  # Example's chunk value
        if not chunk:
            break

        zst_string += chunk.decode("utf-8", "ignore")
        # print(chunk.decode("utf-8", "ignore"))

# String is multiple jsons - turn it into one big one - don't add comma to last line
zst_string = '{"submissions": [' + zst_string.replace("\n{", ",\n{") + "]}"

# print(zst_string)

# I don't know why loading then dumping works but anything else comes back with undefined chars
# Just doing my best, whatever man
zst_json = json.loads(zst_string)  # Properly format as dict
# zst_json = json.dumps(zst_string)  # Turn back into string for file write

for subreddit in subreddits:
    filtered_zst_json = {"submissions": []}

    for submission in zst_json["submissions"]:
        # print(submission["subreddit"])
        if submission["subreddit"] == subreddit:
            filtered_zst_json["submissions"].append(submission)

    zst_json = json.dumps(filtered_zst_json)

    with open(f"./pushshift/json/RS_2023-01_{subreddit}.json", "w") as file_json:
        file_json.write(zst_json)

    # sys.exit()

    # The part we need to access data

    with open(f"./pushshift/json/RS_2023-01.json_{subreddit}", "r") as file_json:
        zst_json = json.load(file_json)

        print(type(zst_json))

        # Do this twice for some reason - first load turns it to a string, loads turns it to dict
        # zst_json = json.loads(zst_json)

        print(type(zst_json))

        print(zst_json["submissions"][0:5])
