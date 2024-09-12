import os
import re
import time
import json
import datetime
import anthropic
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime

api_key = os.getenv('API_KEY')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
SERVICE_ACCOUNT_FILE = '/service_account.json'
PHONE_NUMBER = os.getenv('PHONE_NUMBER')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
RANGE_NAME = 'Sheet1!A1:K'

client = anthropic.Anthropic(api_key=api_key)

def setup_driver():
    try:
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("user-data-dir=felenium")
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--remote-debugging-port=9222")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--no-sandbox")
        path_to_chromedriver = '/app/.chrome-for-testing/chromedriver-linux64/chromedriver'
        service = Service(path_to_chromedriver)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        print(f"Error setting up WebDriver: {e}")
        return None

def check_login_status(driver):
    try:
        search_bar_xpath = '//button[contains(@aria-label , "Search or start new chat")]'
        search_bar = WebDriverWait(driver, 300).until(
            EC.presence_of_element_located((By.XPATH,search_bar_xpath))
        )
        return True
    except Exception as e:
        return False

def login(driver):
    x_path_link_with_phone = "//span[text()='Link with phone number']"
    element = WebDriverWait(driver, 300 ).until(
    EC.element_to_be_clickable((By.XPATH,x_path_link_with_phone ))
    )
    element.click()
    x_path_input_phone = "//input[@aria-label ='Type your phone number.']"
    input_field = WebDriverWait(driver, 300).until(
    EC.presence_of_element_located((By.XPATH, x_path_input_phone))
    )
    phone_number = PHONE_NUMBER 
    input_field.send_keys(phone_number)
    x_path_next_button = "//div[text()='Next']"
    element = WebDriverWait(driver, 30 ).until(
    EC.element_to_be_clickable((By.XPATH,x_path_next_button ))
    )
    element.click()
    x_path_of_code = "//div[@aria-details='link-device-phone-number-code-screen-instructions']"
    while True:
        try:
            element = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH,x_path_of_code ))
            )
            link_code = element.get_attribute('data-link-code')
            print(f"The link code is: {link_code}")
            time.sleep(60)
        except Exception as e : 
            print(f"Some error occured")


def split_date_time_name(a):
    pattern = r'\[(.*?), (.*?)\] (.*?):'
    match = re.match(pattern, a)
    return match.group(1), match.group(2), match.group(3) if match else (None, None, None)

def setup_sheets_api():
    json_str = os.environ.get('SERVICE_FILE_PATH')
    if not json_str:
        raise Exception("Service account credentials not found in environment variables.")
    json_info = json.loads(json_str)
    creds = service_account.Credentials.from_service_account_info(json_info, scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)
    return service.spreadsheets()

def read_group_names_from_sheets(sheets):
    sheet_range = 'Sheet2!A:D'
    result = sheets.values().get(spreadsheetId=SPREADSHEET_ID, range=sheet_range).execute()
    values = result.get('values', [])
    group_names = [value[0] for value in values[1:] if value] if values else []
    return group_names

def send_data_to_sheets(values, sheets):
    body = {'values': values}
    result = sheets.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME,
        valueInputOption='USER_ENTERED',
        insertDataOption='INSERT_ROWS',
        body=body
    ).execute()
    return result

def extract_job_info(message):
    response = client.messages.create(
        model="claude-3-5-sonnet-20240620",
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": f"""Determine if the following message is a job opportunity or referral. If it is either, extract the requested information. If it's not a job opportunity, provide any contact details, links, emails present in the message.

Message: {message}

Provide the information in the following format, don't provide any extra text:
Job/referral opportunity:(reply with yes or no only)
Brief Description(if any): 
Phone numbers provided(if any):
emails provided(if any):
links/URL Provided(if any):

For any information not provided in the message, use "Not Provided"."""
            }
        ]
    )
    return response.content[0].text if isinstance(response.content, list) else response.content

def split_processed_job_details(job_info):
    split_1 = job_info.split('\n')
    return [i.split(': ')[1] for i in split_1]

def extract_and_process(message):
    job_info = extract_job_info(message)
    return split_processed_job_details(job_info)

def extract_messages(driver, group_name):
    x_path_of_all_text_messages = '//div[@role = "row"]//div[contains(@class , "copyable-text")]'
    message_elements = WebDriverWait(driver, 100).until(EC.presence_of_all_elements_located((By.XPATH, x_path_of_all_text_messages)))
    print("Found the group : " + group_name + "with " + len(message_elements) + " text messages")
    data = []
    for message_element in message_elements:
        text_data = message_element.get_attribute("data-pre-plain-text")
        text_message_xpath = './/span[@dir = "ltr"]/span'
        text_message_element = message_element.find_element(By.XPATH, text_message_xpath)
        date_time_name = split_date_time_name(text_data)
        final_data = extract_and_process(text_message_element.text)
        if final_data[0].lower() == "yes":
            append_data = [group_name, date_time_name[1], f"'{date_time_name[2]}", date_time_name[0], final_data[1], f"'{final_data[2]}", final_data[3], final_data[4]]
            data.append(append_data)
    return data

def print_current_date_time():
    current_time = datetime.now()
    formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")
    statement = "Scanning @ "+ formatted_time
    return statement

def main():
    print("Step 1 starts, setup driver")
    driver = setup_driver()
    if not driver:
        return "Driver Not Found"
    driver.get("https://web.whatsapp.com/")
    print("whatsapp opened! waititng for loading")
    time.sleep(60)
    print("Checking login status")
    if(check_login_status(driver) == False):
        time.sleep(15)
        login(driver)
    time.sleep(60)
    sheets = setup_sheets_api()
    statement = print_current_date_time()
    time_values = [[statement]]
    send_data_to_sheets(time_values ,  sheets)
    print("time printed to sheet")
    try:
        group_names = read_group_names_from_sheets(sheets)
        print("The groups to scrape :")
        print(group_names)
    except Exception as e:
        print(f"Error reading group names")
        return
    try:
        for group_name in group_names:
            try:
                x_path = f'//span[@dir = "auto" and @title ="{group_name}"]'
                chathead_element = WebDriverWait(driver,10).until(
                    EC.element_to_be_clickable((By.XPATH, x_path))
                )
                print("Found the group , clicking on it")
                chathead_element.click()
                time.sleep(45)
                extracted_messages = extract_messages(driver, group_name)
                send_data_to_sheets(extracted_messages, sheets)
                print("Extraction complete for group {group_name} Results saved in Google Sheets.")
            except TimeoutException as e :
                print(f"Could not find or click on group: {group_name}")
            except Exception as e:
                print(f"Error processing group {group_name}")
        print("Extraction complete. Results saved in Google Sheets.")
    except Exception as e:
        print(f"An unexpected error occurred")
    finally:
        print("Scraping complete , will close after 30 seconds")
        time.sleep(30)
        driver.quit()

if __name__ == "__main__":
    main()