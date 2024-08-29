from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import os
from selenium.webdriver.common.by import By
import csv
import time
import threading
import re
import anthropic
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.oauth2 import service_account
import json

with open('config.json', 'r') as config_file:
    config = json.load(config_file)

api_key = config['API_KEY']
SPREADSHEET_ID = config['SPREADSHEET_ID']
SERVICE_ACCOUNT_FILE = config['path-to-json-file']

client = anthropic.Anthropic(api_key=api_key)
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

RANGE_NAME = 'Sheet1!A1:K' 

def setup_driver():
    try:
        chrome_options = Options()
        chrome_options.add_argument("user-data-dir=selenium") 
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except WebDriverException as e:
        print(f"Error setting up WebDriver: {e}")
        return None

def split_date_time_name(a):
    pattern = r'\[(.*?), (.*?)\] (.*?):'
    match = re.match(pattern, a)
    if match:
        return match.group(1), match.group(2), match.group(3)
    else:
        return None, None, None

def read_group_names(filename):
    try:
        with open(filename, 'r') as file:
            return [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found.")
        return []
    except IOError as e:
        print(f"Error reading file: {e}")
        return []


def setup_sheets_api():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)
    return service.spreadsheets()


def extract_job_info(message):
    response = client.messages.create(
        model="claude-3-5-sonnet-20240620",
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": f"""Determine if the following message is a job opportunity. If it is, extract the requested information. If it's not a job opportunity, simply respond with "Not a job opportunity".

Message: {message}

If it is a job opportunity, provide the information in the following format :
Role and company:
Experience required:
Specific skills required:
Phone numbers provided(if any):
emails provided(if any):
linkedin URL Provided(if any):

For any information not provided in the message, use "Not Provided"."""
            }
        ]
    )
    job_info_text = response.content[0].text if isinstance(response.content, list) else response.content
    return job_info_text

def split_processed_job_details(job_info):
    if job_info.startswith("Not"):
        return None
    role = experience = skills = phone = emails = links = "Not Provided"
    
    for line in job_info.split('\n'):
        if line.startswith("Role"):
            role = line.split(":", 1)[1].strip()
        elif line.startswith("Experience"):
            experience = line.split(":", 1)[1].strip()
        elif line.startswith("Specific"):
            skills = line.split(":", 1)[1].strip()
        elif line.startswith("Phone"):
            phone = line.split(":", 1)[1].strip()
        elif line.startswith("emails"):
            emails = line.split(":", 1)[1].strip()
        elif line.startswith("linkedin"):
            links = line.split(":", 1)[1].strip()
    
    return [role, experience, skills, phone, emails, links]

def Scrape_and_process_messages(driver, group_name):
    x_path_of_all_text_messages = '//div[@role = "row"]//div[contains(@class , "copyable-text")]'
    message_elements = WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located((By.XPATH, x_path_of_all_text_messages)))
    data = []
    for message_element in message_elements:
        text_data = message_element.get_attribute("data-pre-plain-text")
        text_message_xpath = './/span[@dir = "ltr"]/span'
        text_message_element = message_element.find_element(By.XPATH, text_message_xpath)
        text_message = text_message_element.text 

        splitted_data = split_date_time_name(text_data)
        if all(splitted_data):
            job_info = extract_job_info(text_message)
            splitted_processed_job_details = split_processed_job_details(job_info)
        
        if splitted_processed_job_details is not None:
            append_data = [
                group_name,
                splitted_data[1],
                splitted_data[2],
                splitted_data[0],
                text_message,
                splitted_processed_job_details[0],
                splitted_processed_job_details[1],
                splitted_processed_job_details[2],
                splitted_processed_job_details[3],
                splitted_processed_job_details[4],
                splitted_processed_job_details[5]
            ]
            data.append(append_data)
            return data
        else:
            pass

def send_data_to_sheets(values, sheets):
    body = {
        'values': values
    }
    result = sheets.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME,
        valueInputOption='USER_ENTERED',
        insertDataOption='INSERT_ROWS',
        body=body
    ).execute()
    print(f"{result.get('updates').get('updatedCells')} cells appended.")
    return result

def main():
    driver = setup_driver()
    if not driver:
        return
    sheets = setup_sheets_api()
    group_names = read_group_names('group_names.txt')
    if not group_names:
        print("No group names found or error reading file. Exiting.")
        return
    try:
        driver.get("https://web.whatsapp.com/")
        print("Please scan the QR code if necessary.")
        input("Press Enter after you've logged in to WhatsApp Web...")
        for group_name in group_names:
            try:
                x_path = f'//span[@dir = "auto" and @title ="{group_name}"]'
                chathead_element = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, x_path))
                )
                chathead_element.click()
                print(f"Extracting messages from group: {group_name}")
                time.sleep(2) 
                data = Scrape_and_process_messages(driver, group_name)
                send_data_to_sheets(data, sheets)
            except TimeoutException:
                print(f"Could not find or click on group: {group_name}")
            except Exception as e:
                print(f"Error processing group {group_name}: {e}")
        print("Extraction complete. Results saved in Google Sheets.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
