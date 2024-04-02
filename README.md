# 🗺️[LegendLore](https://legendlore.notion.site/)

![image](https://github.com/EpicRandomGuy2/LegendLore/assets/163953013/2d69b427-658c-4ab2-aa87-c100ece89445)

### The story behind this project
As a DM, I'm hopelessly addicted to maps. The stories they tell, the games we play on them, just the pretty colors and shapes - I began to hoard them like a dragon hoards shiny treasure. Unfortunately my hoard quickly became unmanageable. I couldn't keep up with the rate at which I was acquiring maps, and it became really hard to find the right one for a session, as my maps folder reached sizes that couldn't even be reasonably processed by the software I was using. 

So it was always my goal to organize them in some way. I tried organizing them by folder, by artist, etc., but the amount of time it took to get through even 100 was exhausting. Forget about 100,000. And then, once they were "organized" in some manner, it was still really hard to see them all side-by-side to find the right one.

Eventually I discovered Notion and began to organize my campaign notes in there, and I realized it could lay out images and tag them. And around that time, GPT4-Vision came out, and it could describe images, and even play Geoguessr. The key to organizing all these maps was in these two tools. So I used them to organize my huge, personal collection of maps, and it went so well, I thought hey, why not literally organize every map, ever?

And thus the legend began...

✨ _**My hope is that this tool can also help you find your perfect map! Please support the artists of each map by upvoting the original post, or even subscribing via Patreon!**_ ✨

### Instructions and Tips

- [LegendLore](https://legendlore.notion.site/) updates with new maps at the top of every hour, and updates scores every 6 hours.
- To speed up the search, apply at least one filter! It can be slow to load without it. Other views (seen in the tabs at the top of the filters) may also be faster
- Sorts are VERY slow. By default, it's sorted by `Created ↓` (from newest to oldest). I recommend applying a filter before attempting to do any sorts.
- Multi-tag searches will always be an OR search - ex. `Forest` OR `Fire`. This is an unfortunate limitation of Notion's site hosting, it allows advanced searches on the site's backend but not the public side.
- `Two-Tag Filter` has been provided, to use it, filter by ONE tag, then scroll down to the secondary tag you are searching for.
- If you're finding there are too many world maps in your results, try this: Under the `Tags` filter, there's an option to switch it to `Does Not Contain`. Try that with the `Regional/World` (and if that's not enough, `Town/City`) tags, that should get rid of most of the world maps! You can also filter by subreddit, I'd recommend `r/battlemaps` and `r/dungeondraft` to fully filter out world maps.
![image](https://github.com/EpicRandomGuy2/LegendLore/assets/163953013/026bde74-c852-4be5-8a95-87e46fc71791)

- If all else fails (or you want something very specific, for example "hand-drawn"), you can try searching the word a word (e.g. "drawn") in the `Name` filter or top-right search!
- `Overview` is very slow, but kind of fun to look at. Give it a minute or so to load.
- Switch dark/light mode: CTRL + Shift + L

### Known Issues
- Searching by multiple tags is giving results for either or tag!
    - I know, I tried really hard to bring Advanced Search to the front-end but it's not possible due to Notion limitations. Try the `Two-Tag Filter` instead!
- The same map is in here twice!
    - There are duplicates due to the way "uniqueness" is implemented (a post is "unique" based on its title) - so a slight change in title (across multiple subreddits for example) will cause a duplicate. GPT might also tag each of the duplicates differently.
- This map is tagged wrong!
    - Unfortunately, GPT isn't perfect at tagging. I tried to provide it a little extra context in the form of the map title, which helped, but it still gets things wrong sometimes. There's also some custom logic that collapses `Town/City` maps with more than 8 tags into `Regional/World` due to an issue with how GPT tagged towns (just started throwing everything it could see in there) - sometimes this causes `Town/City` or `Regional/World` to be tagged incorrectly. For fun, take a look at the surprisingly accurate `Giant Skeleton` tag!
- A post from the subreddit is missing in [LegendLore](https://legendlore.notion.site/)!
    - [LegendLore](https://legendlore.notion.site/) can currently only handle Reddit and Imgur links/galleries. Working on support for other common sites like Patreon (public) and Inkarnate in the future!
- Why is this map tagged `Untagged`?
    - Sometimes GPT flips out and refuses to tag an image. When that happens, I ask it again with a more costly, higher resolution version of the image, but if it refuses again, it is what it is and it goes in as `Untagged`. Sorry about that!
- This isn't a map!
    - I went off the general assumption that an image (with a score of >= 1 - i.e. not downvoted, to filter out spam) posted to any of the subreddits were going to be maps. Sometimes they're tokens or similar. These usually get slapped with `Untagged`. 

---

### Technical Stuff

#### This repo contains the code behind [LegendLore](https://legendlore.notion.site/)! It does not contain certain components such as credentials in `credentials.json`, MongoDB, or Docker.
#### Currently tracks 5 subreddits: 
1. r/battlemaps
2. r/dndmaps
3. r/dungeondraft
4. r/FantasyMaps
5. r/inkarnate


#### [LegendLore](https://legendlore.notion.site/) is a database consisting of a few key components:
1. Python scripts - The Python scripts in this repo enable [LegendLore](https://legendlore.notion.site/) to find/tag/track state/push new maps
2. Reddit - All maps are pulled from publicly available images on the above subreddits.
3. MongoDB - Data on every post is stored on a MongoDB backend and processed later. At the time of writing, there are about 100k maps, and an additional 40k posts in the DB that could not be sent to Notion - either because they're not maps (question posts, spam, etc.) or the image links aren't yet supported.
4. GPT4-Vision - Analyzes the maps and tags them based on a list of tags provided. This was the game-changer that finally let me fulfill the dream of organizing my map backlog.
5. Docker/Cron - On my home server, I have two docker containers running - one every hour that just pushes new maps to Notion, and one every 6 hours that updates the scores of all maps less than a week old (to enable fair and accurate score sorting, I decided on a week cause scores have largely settled by then).
6. Notion - The lovely visual database and web host that lets me show all the maps without having to worry about all that front-end stuff.

#### Can I use [LegendLore](https://legendlore.notion.site/) for `insert thing here`?
Sure! It's a bit purpose built at the moment, but using config.py, you can hook it up to your own Notion DB, MongoDB, GPT token, and subreddits and run it on whatever you want, doesn't even really have to be maps. Do keep in mind that the GPT calls cost a bit of money (like 0.3 cents per image on average).

#### Can I help tag some untagged maps?
I would love to say yes, but unfortunately I can't allow limited edit access at the moment - it's all or nothing. In the future, if I can figure out how to allow contributors, I would love your help!

#### I would like to report a bug or contribute to the project!
Thank you! Feel free to use the Issues tab above to submit a bug, or make a pull request/fork to contribute!

#### I would like my content to be removed from this tool!
Understood! Please shoot a PM to u/EpicRandomGuy2 on Reddit and I will gladly remove your content!
