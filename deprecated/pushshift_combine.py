import json
import sys
import os

# This script deals with pushshift zst data, was used to build out LegendLore on posts > 1000 posts ago (Reddit API's limit)
# Builds a big, proper json file out of every year/month's data - it switched from yearly to monthly at some point, ugh
# Honestly don't use this for anything it's terrible

# print(json.load(open("./pushshift/json/test_submissions.json", "r")))

filename = ""

subreddits_combined_json = {
    "battlemaps": {"submissions": []},
    "dndmaps": {"submissions": []},
    "dungeondraft": {"submissions": []},
    "FantasyMaps": {"submissions": []},
    "inkarnate": {"submissions": []},
}

submission_jsons = os.listdir("./pushshift/json/")

submission_jsons.remove("Completed")

print(submission_jsons)

for filename in submission_jsons:
    with open(f"./pushshift/json/{filename}", "r") as json_file:
        for key in subreddits_combined_json:
            if key in filename:
                a_json = json.load(json_file)
                subreddits_combined_json[key]["submissions"].extend(
                    a_json["submissions"]
                )

for subreddit in subreddits_combined_json:
    with open(f"./pushshift/json/{subreddit}_2024.json", "w") as file_json_final:
        file_json_final.write(json.dumps(subreddits_combined_json[subreddit]))
