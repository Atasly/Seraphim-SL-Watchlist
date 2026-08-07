# Seraphim Weekend Sales Scraper + Site Generator

Scrapes Second Life weekend-sale galleries (Seraphim, AltSL, Facebook albums, and
other external galleries) for stores on your watchlist, saves the matches to
`matches.json`, and renders them into a static, dark, magazine-style website in
`docs/` that can be hosted on GitHub Pages.

## Note of intent

It is getting painful to trudge through the sea of AI slop pictures cropping more often every weekend sales.
For those interested in modding outfits, so many weekend sales end up cluttering the search with their no mod permissions.
This is a tool that aims to help against that.

All credits go to [SeraphimSL](https://www.seraphimsl.com/) creators for their invaluable work.
Without their presence and their work, this tool wouldn't function at all.

This tool is meant to be run once per week, on the saturday-sunday, to scrape and build the website.
By design it will only query lower res pictures from SeraphimSL first, when scrolling down to the matching tab. 
Higher res pictures will be fetched if fullscreen is turned on.
This matches SeraphimSL behaviour.

## Files

| File                                  | Purpose                                              |
| ------------------------------------- | ---------------------------------------------------- |
| `seraphim-weekend-scraper.py`     | The scraper (produces `matches.json`)                |
| `generate_site.py`                    | The site generator (produces `docs/index.html`)      |
| `Stores.txt`                          | Watchlist #1: one store name per line                |
| `Stores - fatpack.txt`                | Watchlist #2: weekend sales that are mods in fatpack |
| `Stores - build.txt`                  | Watchlist #3: weekend sales for building             |
| `fb_cookies.json`                     | Facebook session cookies (for Facebook albums only)  |
| `matches.json`                        | Scraper output (watchlist #1)                        |
| `matches - fatpack.json`              | Scraper output (watchlist #2)                        |
| `matches - build.json`                | Scraper output (watchlist #3)                        |
| `docs/index.html`                     | Generated website page (one tab per watchlist)       |

The fatpack/build split is loose: a store can land in one list or the other
depending on what its weekend sale happens to be, so the boundary is fuzzy.

## One-time setup

```powershell
python -m pip install requests beautifulsoup4
```

Facebook photo albums are scraped through a headless browser; install Playwright
only if you want those:

```powershell
python -m pip install playwright
python -m playwright install chromium
```

## Stores.txt

One store name per line, case-insensitive, exact match. Lines starting with `#`
are ignored. `*B.D.R.*` style wildcards match anywhere.

```
# my watchlist
Moon
muse
*B.D.R.*
```

## fb_cookies.json (Facebook only)

Facebook albums require your session cookies. Create `fb_cookies.json` next to
the script with one cookie per line:

```
c_user:"<id>"
xs:"<token>"
```

Keep this file private (do not commit it), and re-export the cookies whenever
they expire.

## Scrape

Basic run — everything from the most recent Friday onward, written to
`matches.json`:

```powershell
python seraphim-weekend-scraper.py
```

Useful options:

```powershell
# custom output file
python seraphim-weekend-scraper.py --output matches.json

# custom store list
python seraphim-weekend-scraper.py --stores-file mystores.txt

# only events on/after a specific date
python seraphim-weekend-scraper.py --since-date 2026-08-01

# verbose debug logging (stderr)
python seraphim-weekend-scraper.py --debug

# path to a non-default Facebook cookie file
python seraphim-weekend-scraper.py --fb-cookies myfb_cookies.json
```

Other sources:

```powershell
python seraphim-weekend-scraper.py --source altsl --listing-url https://altsl.com/
python seraphim-weekend-scraper.py --source wordpress --listing-url https://35lsunday.com/
python seraphim-weekend-scraper.py --source wix --listing-url https://hypeeventssl.wixsite.com/hypeeventssl/miix-weekend-gallery
python seraphim-weekend-scraper.py --source evoshop --listing-url https://home.evoshopevent.com/
```

## Build the website

```powershell
python generate_site.py
```

This reads `matches.json` and writes `docs/index.html` (plus a copy of the data
at `docs/matches.json`).

### Multiple watchlists (tabs)

One scrape run can match against several store lists: repeat `--stores-file`
with one `--output` per list (same order). Every gallery is fetched only once,
then checked against each list — no duplicate requests:

```powershell
python seraphim-weekend-scraper.py --stores-file "Stores.txt" --output "matches.json" --stores-file "Stores - fatpack.txt" --output "matches - fatpack.json" --stores-file "Stores - build.txt" --output "matches - build.json"
```

Then build one page with a tab per list:

```powershell
python generate_site.py --tab-label Stores --input "matches.json" --tab-label "Stores - fatpack" --input "matches - fatpack.json" --tab-label "Stores - build" --input "matches - build.json"
```

If you skip `--tab-label`, the tab is named after the input file's name.
The first list becomes the tab shown by default.

You can also list every watchlist in one right-aligned tab, grouped by the
`# A`, `# B`, ... category headers in each file:

```powershell
python generate_site.py --stores-file "Stores.txt" --stores-file "Stores - fatpack.txt" --stores-file "Stores - build.txt"
```

Other options:

```powershell
python generate_site.py --input matches.json --output docs/index.html --title "Weekend Sale Matches"
```

## Typical run

Scrape and rebuild:

```powershell
python seraphim-weekend-scraper.py --stores-file "Stores.txt" --output "matches.json" --stores-file "Stores - fatpack.txt" --output "matches - fatpack.json" --stores-file "Stores - build.txt" --output "matches - build.json"
```

```powershell
python generate_site.py --tab-label "single" --input "matches.json" --tab-label "fatpack" --input "matches - fatpack.json" --tab-label "build" --input "matches - build.json" --stores-file "Stores.txt" --stores-file "Stores - fatpack.txt" --stores-file "Stores - build.txt"
```

## Publish on GitHub Pages

1. Make this folder a git repository and push it to GitHub.
2. In the repository settings, enable Pages: **Deploy from a branch** →
   `main` → folder `/docs`.
3. After each scrape, re-run the typical command above and push the updated
   `docs/` folder.
