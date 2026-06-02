# scholarship-scraper

The US Dept of Labor provides a website with a directory of 10,000 scholarships.  This tool scrapes information from that website in pursuit of the 501c3 entities that manage those scholarships.  

## Prerequisites

Activate ChromeDriver.exe

If you don't have these Python extensions, then run:

* pip install requests
* pip install beautifulsoup4
* pip install selenium
* pip install pandas

Download scraper.py from GitHub repository and place it in your working directory.

## Context

This workspace has a single python program scraper.py. scraper.py goes to

https://www.careeronestop.org/Toolkit/Training/find-scholarships.aspx

and downloads 9 attributes of 10,000 scholarships.

The first 8 attributes come from the first page at the website, but selecting a link on that page, the program goes
one level further to get further detail, in this case 'more information URL'.

## Operation

### Features

* Helper function `extract_more_info_url()` extracts the URL from detail pages
* Test mode enabled: scrapes only first 20 scholarships from the first page
* Row counter tracks progress and stops at limit
* Delays implemented (0.75s after each detail page, 2s between pages)
* Comprehensive logging for debugging
* Robust error handling with try-finally to ensure WebDriver closes
* No virtual environment required

### Test versus Production

Test

* `TEST_MODE = True` and `SCHOLARSHIP_LIMIT = 20`
* Will scrape only the first page: `range(1, 2)`
* Expected runtime: 2-5 minutes for 20 scholarships

To transition to production (after testing passes):

* Change `TEST_MODE = False` and increase `SCHOLARSHIP_LIMIT = 10000`
* Change `range(1, 2)` to `range(1, 21)` to loop through all 20 pages

Run with

```powershell
python scraper.py
```

## Output

The output goes to a csv file with 9 columns and as many rows as scholarships.   The 9 columns are labeled

1. ID
2. Award Name
3. Organization
4. Purpose
5. Level of Study
6. Award Type
7. Award Amount
8. Deadline
9. More Info URL

In production, the output csv file (called scholarships.csv) has 10,000 rows which was the entirety of what was available from the Labor Department's CareerOneStop website.

## What Happened Next

This scraper is part of a tool set for identifying entities at which to endow scholarships.  After the scholarship scraper was run, Rada took the output (which was a 22 megabyte csv file of 10,000 scholarships) and further processed it.  The routine followed these steps:

* sort the file by frequency of organization sponsoring the scholarship,
* take the two hundred most frequently occurring organizations, and
* feed their URLS into the 'minimum endowment scraper' which identifies how much money a donor must give to endow a named, targeted scholarship.

Often an organization does not provide information on its website as to a minimum donor amount that would endow a named, targeted scholarship, but in this case, of those two-hundred, sixty explicitly provided that information.

## Authors

* **Roy Rada**: Project lead, architecture, some coding, testing, refining parameters, maintaining
* **Microsoft Copilot**: Collaborative assistance in coding and system design


