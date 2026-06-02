import csv
import json
import logging
import os
import time

from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException, NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


INPUT_CSV = "scholarships.csv"
OUTPUT_CSV = "scholarships_recovered.csv"
CHECKPOINT_FILE = "scrape_checkpoint.json"

START_ROW = 6739
END_ROW = 10000
PAGE_SIZE = 500
TOTAL_PAGES = 20

AUTO_RESUME = True
CHECKPOINT_EVERY = 25
RETRY_LIMIT = 2

DETAIL_DELAY_SECONDS = 0.75
PAGE_DELAY_SECONDS = 2

HEADER = [
    "ID",
    "Award Name",
    "Organization",
    "Purpose",
    "Level of Study",
    "Award Type",
    "Award Amount",
    "Deadline",
    "More Information URL",
]


def build_driver(chrome_options):
    return webdriver.Chrome(options=chrome_options)


def safe_get(driver, chrome_options, url, context, retries=RETRY_LIMIT):
    attempt = 0
    while True:
        try:
            driver.get(url)
            return driver
        except InvalidSessionIdException:
            attempt += 1
            if attempt > retries:
                raise
            logger.warning("Invalid session during %s. Recreating driver (%s/%s).", context, attempt, retries)
            try:
                driver.quit()
            except Exception:
                pass
            driver = build_driver(chrome_options)


def normalize_row(row):
    if len(row) < len(HEADER):
        return row + [""] * (len(HEADER) - len(row))
    return row[: len(HEADER)]


def read_existing_rows(file_path):
    if not os.path.exists(file_path):
        logger.warning("Input file %s was not found. Continuing with empty baseline.", file_path)
        return []

    with open(file_path, "r", newline="", encoding="utf-8") as f:
        reader = list(csv.reader(f))

    if not reader:
        return []

    data_rows = reader[1:]
    return [normalize_row(row) for row in data_rows]


def load_checkpoint():
    if not AUTO_RESUME or not os.path.exists(CHECKPOINT_FILE):
        return None

    try:
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            checkpoint = json.load(f)
    except Exception as e:
        logger.warning("Could not read checkpoint file: %s", e)
        return None

    if checkpoint.get("start_row") != START_ROW or checkpoint.get("end_row") != END_ROW:
        return None

    return checkpoint


def save_checkpoint(last_completed_row):
    checkpoint = {
        "start_row": START_ROW,
        "end_row": END_ROW,
        "last_completed_row": last_completed_row,
        "updated_epoch": int(time.time()),
    }
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f)


def clear_checkpoint_if_done(last_completed_row):
    if last_completed_row >= END_ROW and os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)


def extract_listing_page_scholarships(driver, page_num):
    rows = driver.find_elements(By.CSS_SELECTOR, "table.cos-table-responsive tbody tr")
    logger.info("Found %s listing rows on page %s", len(rows), page_num)

    scholarships = []
    for row_index, row in enumerate(rows, 1):
        try:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) < 5:
                continue

            award_td = cells[0]

            try:
                award_link = award_td.find_element(By.CSS_SELECTOR, ".detailPageLink a")
                award_name = award_link.text.strip()
                href = award_link.get_attribute("href") or ""
                award_id = href.split("scholarshipId=")[-1] if "scholarshipId=" in href else ""
            except NoSuchElementException:
                logger.debug("No award link found on page %s row %s", page_num, row_index)
                award_name = ""
                award_id = ""

            inner_divs = award_td.find_elements(By.XPATH, "./div/div")
            org_text = ""
            purpose_text = ""
            for div in inner_divs:
                div_text = div.text.strip()
                if div_text.startswith("Organization:"):
                    org_text = div_text.replace("Organization:", "").strip()
                elif div_text.startswith("Purposes:"):
                    purpose_text = div_text.replace("Purposes:", "").strip()

            scholarships.append(
                {
                    "award_id": award_id,
                    "award_name": award_name,
                    "organization": org_text,
                    "purpose": purpose_text,
                    "level_of_study": cells[1].text.strip(),
                    "award_type": cells[2].text.strip(),
                    "award_amount": cells[3].text.strip(),
                    "deadline": cells[4].text.strip(),
                }
            )
        except Exception as e:
            logger.error("Error parsing listing row %s on page %s: %s", row_index, page_num, e)

    return scholarships


def extract_more_info_url(driver, chrome_options, scholarship_id):
    if not scholarship_id:
        return driver, ""

    detail_url = (
        "https://www.careeronestop.org/GetMyFuture/Toolkit/"
        f"find-scholarships-detail.aspx?&scholarshipId={scholarship_id}"
    )

    try:
        driver = safe_get(driver, chrome_options, detail_url, f"detail page scholarshipId={scholarship_id}")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CLASS_NAME, "cos-table-detail")))

        rows = driver.find_elements(By.CSS_SELECTOR, "table.cos-table-detail tbody tr")
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) < 2:
                continue
            if "For more information" in cells[0].text.strip():
                try:
                    link = cells[1].find_element(By.TAG_NAME, "a")
                    return driver, (link.get_attribute("href") or "")
                except NoSuchElementException:
                    return driver, ""

        return driver, ""
    except TimeoutException:
        logger.warning("Timeout reading detail page for scholarship ID %s", scholarship_id)
        return driver, ""
    except Exception as e:
        logger.error("Error reading detail page for scholarship ID %s: %s", scholarship_id, e)
        return driver, ""


def scrape_range(chrome_options, effective_start):
    scraped_rows = {}
    start_page = ((effective_start - 1) // PAGE_SIZE) + 1
    end_page = ((END_ROW - 1) // PAGE_SIZE) + 1

    if start_page < 1:
        start_page = 1
    if end_page > TOTAL_PAGES:
        end_page = TOTAL_PAGES

    logger.info("Scraping target range rows %s-%s (pages %s-%s)", effective_start, END_ROW, start_page, end_page)

    driver = build_driver(chrome_options)
    last_completed_row = effective_start - 1

    try:
        for page_num in range(start_page, end_page + 1):
            list_url = (
                "https://www.careeronestop.org/Toolkit/Training/"
                f"find-scholarships.aspx?&curpage={page_num}&pagesize={PAGE_SIZE}"
            )

            driver = safe_get(driver, chrome_options, list_url, f"listing page {page_num}")

            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "cos-table-responsive"))
                )
            except TimeoutException:
                logger.warning("Timeout waiting for listing table on page %s", page_num)
                continue

            page_scholarships = extract_listing_page_scholarships(driver, page_num)
            page_start_row = ((page_num - 1) * PAGE_SIZE) + 1

            local_start = max(1, effective_start - page_start_row + 1)
            local_end = min(len(page_scholarships), END_ROW - page_start_row + 1)

            if local_start > local_end:
                continue

            for local_row in range(local_start, local_end + 1):
                global_row = page_start_row + local_row - 1
                scholarship = page_scholarships[local_row - 1]

                driver, more_info_url = extract_more_info_url(
                    driver,
                    chrome_options,
                    scholarship["award_id"],
                )

                scraped_rows[global_row] = [
                    scholarship["award_id"],
                    scholarship["award_name"],
                    scholarship["organization"],
                    scholarship["purpose"],
                    scholarship["level_of_study"],
                    scholarship["award_type"],
                    scholarship["award_amount"],
                    scholarship["deadline"],
                    more_info_url,
                ]

                last_completed_row = global_row
                logger.info("[%s] Scraped row %s: %s", len(scraped_rows), global_row, scholarship["award_name"])

                if len(scraped_rows) % CHECKPOINT_EVERY == 0:
                    save_checkpoint(last_completed_row)

                time.sleep(DETAIL_DELAY_SECONDS)

            time.sleep(PAGE_DELAY_SECONDS)

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    return scraped_rows, last_completed_row


def write_recovered_csv(existing_rows, scraped_rows):
    total_rows = max(len(existing_rows), END_ROW)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)

        for row_num in range(1, total_rows + 1):
            if row_num in scraped_rows:
                writer.writerow(scraped_rows[row_num])
            elif row_num <= len(existing_rows):
                writer.writerow(normalize_row(existing_rows[row_num - 1]))
            else:
                writer.writerow([""] * len(HEADER))


def main():
    if START_ROW < 1 or END_ROW < START_ROW:
        raise ValueError("Invalid range. START_ROW must be >= 1 and END_ROW must be >= START_ROW.")

    checkpoint = load_checkpoint()
    if checkpoint:
        effective_start = max(START_ROW, checkpoint.get("last_completed_row", START_ROW - 1) + 1)
        logger.info("Resuming from checkpoint at row %s", effective_start)
    else:
        effective_start = START_ROW

    existing_rows = read_existing_rows(INPUT_CSV)

    options = Options()
    # Uncomment for headless mode:
    # options.add_argument("--headless")
    options.add_argument("--disable-gpu")

    scraped_rows = {}
    last_completed_row = effective_start - 1

    if effective_start <= END_ROW:
        scraped_rows, last_completed_row = scrape_range(options, effective_start)

    write_recovered_csv(existing_rows, scraped_rows)
    save_checkpoint(last_completed_row)
    clear_checkpoint_if_done(last_completed_row)

    logger.info("Done. Wrote recovered output to %s", OUTPUT_CSV)
    logger.info("Range processed: %s-%s", effective_start, END_ROW)


if __name__ == "__main__":
    main()
