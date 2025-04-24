import requests
import io
import pdfplumber
from openai import OpenAI
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from pydantic import BaseModel
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import time
import os
from typing import List, Dict, Optional
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from datetime import datetime
from selenium.common.exceptions import ElementClickInterceptedException
import tempfile
from zoneinfo import ZoneInfo
import json
import asyncio
import base64
from dotenv import load_dotenv
import shutil

load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment flag
IsProduction = True  # Set to True in production on Railway.app

# Initialize FastAPI app
app = FastAPI()
executor = ThreadPoolExecutor(max_workers=8)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define Pydantic models
class LoginRequest(BaseModel):
    url: str
    username: str
    password: str

class CalculationData(BaseModel):
    processedData: List[Dict]
    inputs: Dict
    totalAccumulatedMP: float

class FormData(BaseModel):
    isCorporateCustomer: bool
    isPolicyHolder: bool
    surname: str
    givenName: str
    chineseName: str
    insuranceAge: str
    gender: str
    isSmoker: bool
    basicPlan: str
    currency: str
    notionalAmount: str
    premiumPaymentPeriod: str
    premiumPaymentMethod: str
    useInflation: bool
    proposalLanguage: str

class OtpRequest(BaseModel):
    session_id: str
    otp: str
    calculation_data: CalculationData
    formData: FormData

class RetryRequest(BaseModel):
    session_id: str
    new_notional_amount: str

# Global storage
sessions = {}  # session_id -> {"driver": driver, "form_data": form_data}
session_queues = {}  # session_id -> asyncio.Queue
TIMEOUT = 120

# Helper function to run synchronous tasks in a thread
async def run_in_thread(func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, func, *args)

# Helper function to log messages and put into queue
def log_message(message: str, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    if IsProduction:
        logger.info(message)
    else:
        print(message)
    asyncio.run_coroutine_threadsafe(queue.put(message), loop)

# Selenium worker for initial login
def selenium_worker(session_id: str, url: str, username: str, password: str, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    try:
        options = webdriver.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument("--disable-gpu")
        # Enable performance logging
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
        # Remove download directory settings since we won't save to disk
        prefs = {
            "download.prompt_for_download": False,
            "plugins.always_open_pdf_externally": True,  # Still force PDF download behavior
        }
        options.add_experimental_option("prefs", prefs)

        if IsProduction:
            options.add_argument('--headless')
            driver = webdriver.Remote(command_executor='https://standalone-chrome-production-57ca.up.railway.app', options=options)
        else:
            driver = webdriver.Chrome(options=options)

        driver.get(url)

        login_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.ID, "user"))
        )
        login_field.send_keys(username)
        log_message("username sent", queue, loop)

        driver.find_element(By.ID, 'password').send_keys(password)
        log_message("password sent", queue, loop)

        driver.find_element(By.XPATH, '//*[@id="form"]/button').click()
        log_message("login button clicked", queue, loop)

        mailOption = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, "//label[contains(., '已登記的電郵地址')]"))
        )
        mailOption.click()
        log_message("mailOption clicked", queue, loop)

        sendOtpRequestButton = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//*[@id="otp"]/div[2]/button[1]'))
        )
        sendOtpRequestButton.click()
        log_message("sendOtpRequestButton clicked", queue, loop)
        log_message("一次性密碼從電郵發放中...", queue, loop)

        sessions[session_id] = {"driver": driver}
    except Exception as e:
        log_message(f"Selenium error: {str(e)}", queue, loop)
        if session_id in sessions:
            driver = sessions.pop(session_id).get("driver")
            if driver:
                driver.quit()
        raise

# Helper function to perform checkout and capture PDF from network
def perform_checkout(driver, notional_amount: str, form_data: Dict, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    try:
        # Click "保費摘要"
        policy_field = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.XPATH, '/html/body/app-root/qq-base-structure/mat-drawer-container/mat-drawer-content/div/div/div/qq-left-tab/div/button[7]/span[2]/div'))
        )
        policy_field.click()
        log_message("保費摘要 clicked", queue, loop)

        # Custom condition to check for system message or view button
        class EitherElementLocated:
            def __init__(self, locator1, locator2):
                self.locator1 = locator1  # System messages
                self.locator2 = locator2  # View button

            def __call__(self, driver):
                system_messages = driver.find_elements(*self.locator1)
                for msg in system_messages:
                    if msg.is_displayed() and any(keyword in msg.text for keyword in ["所達年齡", "總每年保費不能少於"]):
                        return {"type": "system_message", "element": msg}
                try:
                    view_element = driver.find_element(*self.locator2)
                    if view_element.is_displayed():
                        return {"type": "view_button", "element": view_element}
                except NoSuchElementException:
                    pass
                return False

        system_message_locator = (By.XPATH, "//div[@class='control-message']//li")
        view_button_locator = (By.XPATH, "/html/body/app-root/qq-base-structure/mat-drawer-container/mat-drawer-content/div/div/div/div/div/qq-premium-summary/div/div[3]/button/span[2]")

        result = WebDriverWait(driver, 30).until(
            EitherElementLocated(system_message_locator, view_button_locator)
        )

        if result["type"] == "system_message":
            system_message = result["element"].text
            log_message(f"系統信息: {system_message}", queue, loop)
            cleaned_amount = notional_amount.replace(',', '')
            integer_part = cleaned_amount.split('.')[0]
            formatted_amount = f"{int(integer_part):,}"
            return {
                "status": "retry",
                "system_message": f"{system_message}\n 對上一次輸入的名義金額為${formatted_amount}"
            }
        elif result["type"] == "view_button":
            view_button = result["element"]
            view_button.click()
            log_message("名義金額而獲通過", queue, loop)
            log_message("檢視建議書 clicked", queue, loop)

            # Enter filename in save input field
            save_input_field = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//input[@matinput and @maxlength='80']"))
            )
            tz_gmt8 = ZoneInfo("Asia/Shanghai")
            timestamp = datetime.now(tz_gmt8).strftime("%Y%m%d%H%M")
            filename = f"宏摯傳承保障計劃_{timestamp}"
            save_input_field.clear()
            save_input_field.send_keys(filename)

            # Click save button
            save_button = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, "//mat-dialog-container//div[@class='dialog-buttons']/button[contains(., '儲存')]"))
            )
            try:
                save_button.click()
                log_message("儲存 button successfully clicked", queue, loop)
            except:
                ActionChains(driver).move_to_element(save_button).pause(0.5).click().perform()
                log_message("儲存2 button successfully clicked", queue, loop)

            # Select proposal language
            if str(form_data['proposalLanguage']) == "zh":
                proposal_language_radio = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@value='zh']/ancestor::div[contains(@class, 'mdc-radio')]"))
                )
                proposal_language_radio.click()
                log_message("proposalLanguage_radio = zh", queue, loop)
            elif str(form_data['proposalLanguage']) == "sc":
                proposal_language_radio = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@value='sc']/ancestor::div[contains(@class, 'mdc-radio')]"))
                )
                proposal_language_radio.click()
                log_message("proposalLanguage_radio = sc", queue, loop)
            else:
                proposal_language_radio = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@value='zh']/ancestor::div[contains(@class, 'mdc-radio')]"))
                )
                proposal_language_radio.click()
                log_message("proposalLanguage_radio = zh (default)", queue, loop)

            # Check "所有年期"
            label = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//label[.//div[text()='所有年期']]"))
            )
            label.click()
            log_message("所有年期 checked", queue, loop)

            # Click print button to trigger PDF download
            print_button = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, "//cpos-button[.//span[contains(., '列印建議書')]]//button[contains(@class, 'agent-btn')]"))
            )
            try:
                print_button.click()
                log_message("列印建議書 button clicked successfully", queue, loop)
            except:
                ActionChains(driver).move_to_element_with_offset(print_button, 5, 5).pause(0.3).click().perform()
                log_message("列印建議書2 button clicked successfully", queue, loop)

            time.sleep(15)
            log_message("列印中, 請稍後..." , queue, loop)
            # Capture PDF content from network response
            pdf_content = None
            start_time = time.time()
            while time.time() - start_time < 60:  # Wait up to 60 seconds
                logs = driver.get_log('performance')
                for log in logs:
                    message = json.loads(log['message'])['message']
                    if message['method'] == 'Network.responseReceived':
                        response = message['params']['response']
                        if response['mimeType'] == 'application/pdf':
                            request_id = message['params']['requestId']
                            body = driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': request_id})
                            if body['base64Encoded']:
                                pdf_content = base64.b64decode(body['body'])
                            else:
                                pdf_content = body['body'].encode()
                            break
                if pdf_content:
                    break
                time.sleep(1)
            else:
                raise TimeoutException("PDF response not found within timeout")

            log_message("PDF content captured from network response", queue, loop)

            # Process PDF content in memory
            pdf_file = io.BytesIO(pdf_content)
            with pdfplumber.open(pdf_file) as pdf:
                text = ""
                for page in pdf.pages:
                    text += page.extract_text() or ""
            log_message("Text extracted from PDF", queue, loop)

            # DeepSeek API call
            system_prompt = (
                "幫我在「款項提取說明－退保價值」表格中找出65歲和85歲的「款項提取後的退保價值總額(C) + (D)」的數值,"
                "答案要儘量簡單直接輸出一句'65歲和85歲的「款 title提取後的退保價值總額(C) + (D)」的數值是 **HKDxxxxxx**',數值前面要加上2個*號"
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ]

            client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                stream=False
            )
            ai_response = response.choices[0].message.content
            log_message(f"Deepseek reply={ai_response}", queue, loop)

            # Clean up
            # driver.close()
            # driver.switch_to.window(driver.window_handles[0])
            log_message("建議書已成功建立及下載到計劃易系統中!", queue, loop)

            return {"status": "success", "ai_response": ai_response}

    except TimeoutException as e:
        log_message(f"Error: {str(e)}", queue, loop)
        raise Exception(str(e))

# Worker to verify OTP and fill form
def verify_otp_worker(session_id: str, otp: str, calculation_data: Dict, form_data: Dict, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    session_data = sessions.get(session_id)
    if not session_data or "driver" not in session_data:
        log_message("Invalid session ID", queue, loop)
        raise ValueError("Invalid session ID")
    driver = session_data["driver"]
    session_data["form_data"] = form_data

    try:
        otp = otp.strip()
        for i in range(6):
            pin_xpath = f'//*[@id="pin_{i}"]'
            otp_pin = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, pin_xpath))
            )
            otp_pin.send_keys(otp[i])
            log_message(f"otp_pin_{otp[i]} entered", queue, loop)

        otp_continual_button = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="verify"]/div[2]/button[1]'))
        )
        driver.execute_script("arguments[0].click();", otp_continual_button)
        log_message("繼續 clicked, 請稍後...", queue, loop)

        try:
            WebDriverWait(driver, 20).until(
                lambda d: d.find_element(By.XPATH, "//button[.//span[text()='製作建議書']]")
            )
        except TimeoutException:
            log_message("您輸入的一次性密碼不正確", queue, loop)
            raise Exception("您輸入的一次性密碼不正確")

        proposal_button = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//button[.//span[text()='製作建議書']]"))
        )
        proposal_button.click()
        log_message("Proposal button clicked", queue, loop)

        if form_data['isCorporateCustomer']:
            isCorporateCustomer_field = WebDriverWait(driver, TIMEOUT).until(
                EC.presence_of_element_located((By.ID, "mat-mdc-checkbox-1-input"))
            )
            isCorporateCustomer_field.click()
            log_message("Clicked isCorporateCustomer checkbox", queue, loop)

        if form_data['isPolicyHolder']:
            isPolicyHolder_field = WebDriverWait(driver, TIMEOUT).until(
                EC.presence_of_element_located((By.ID, 'mat-radio-5-input'))
            )
            isPolicyHolder_field.click()
            log_message("isPolicyHolder is true", queue, loop)
        else:
            isPolicyHolder_field = WebDriverWait(driver, TIMEOUT).until(
                EC.presence_of_element_located((By.ID, 'mat-radio-6-input'))
            )
            isPolicyHolder_field.click()
            log_message("isPolicyHolder is false", queue, loop)

        sureName_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//div[label[contains(text(), "英文姓氏")]]//input'))
        )
        sureName_field.clear()
        sureName_field.send_keys(str(form_data['surname']))
        log_message("Surname field filled", queue, loop)

        givenName_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//div[label[contains(text(), "英文名字")]]//input'))
        )
        givenName_field.clear()
        givenName_field.send_keys(str(form_data['givenName']))
        log_message("Given name field filled", queue, loop)

        if form_data['chineseName']:
            chineseName_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, '//div[label[contains(text(), "中文姓名")]]//input'))
            )
            chineseName_field.clear()
            chineseName_field.send_keys(str(form_data['chineseName']))
            log_message("chineseName_field filled", queue, loop)

        age_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//div[label[contains(text(), "投保年齡")]]//input'))
        )
        age_field.clear()
        age_field.send_keys(str(calculation_data['inputs'].get('age', '')))
        log_message(f"age_field field filled={str(calculation_data['inputs'].get('age', ''))}", queue, loop)

        if "Female" in form_data['gender']:
            gender_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, "//mat-radio-button[@value='Female']"))
            )
            gender_field.click()
            log_message("gender_field Female clicked", queue, loop)

        if form_data['isSmoker']:
            isSmoker_field = WebDriverWait(driver, TIMEOUT).until(
                EC.element_to_be_clickable((By.XPATH, "//mat-radio-button[@value='Yes']"))
            )
            isSmoker_field.click()
            log_message("isSmoker_field yes clicked", queue, loop)

        basicPlan_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '/html/body/app-root/qq-base-structure/mat-drawer-container/mat-drawer-content/div/div/div/qq-left-tab/div/button[2]/span[2]/div'))
        )
        basicPlan_field.click()
        log_message("基本計劃 page clicked", queue, loop)

        basicPlan_select_field = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//label[contains(text(), '基本計劃')]/following-sibling::mat-form-field//mat-select"))
        )
        driver.execute_script("arguments[0].click();", basicPlan_select_field)
        log_message("基本計劃 Dropdown clicked", queue, loop)

        if 'GS' in str(form_data['basicPlan']):
            basicPlan_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.element_to_be_clickable((By.XPATH, "//div[@id='mat-select-4-panel']//mat-option[.//span[contains(text(), '(GS)')]]"))
            )
            basicPlan_option_field.click()
            log_message("基本計劃 GS option clicked", queue, loop)

        numberOfYear_select_field = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//label[contains(text(), '保費繳付期')]/following-sibling::mat-form-field//mat-select"))
        )
        driver.execute_script("arguments[0].click();", numberOfYear_select_field)
        log_message("保費繳付期 Dropdown clicked", queue, loop)

        number_of_years = str(form_data['premiumPaymentPeriod'])
        log_message(f"number_of_years={number_of_years}", queue, loop)

        if '3' in number_of_years:
            numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, '//mat-option[contains(., "3")]'))
            )
            numberOfYear_option_field.click()
            log_message("保費繳付期 3 year clicked", queue, loop)
        elif '15' in number_of_years:
            numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, '//mat-option[contains(., "15")]'))
            )
            numberOfYear_option_field.click()
            log_message("保費繳付期 15 year clicked", queue, loop)
        elif '10' in number_of_years:
            numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, '//mat-option[contains(., "10")]'))
            )
            numberOfYear_option_field.click()
            log_message("保費繳付期 10 year clicked", queue, loop)
        elif '5' in number_of_years:
            numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, '//mat-option[contains(., "5")]'))
            )
            numberOfYear_option_field.click()
            log_message("保費繳付期 5 year clicked", queue, loop)

        worryFreeSelection = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//label[contains(text(), '無憂選')]/following-sibling::mat-form-field//mat-select"))
        )
        driver.execute_script("arguments[0].click();", worryFreeSelection)
        log_message("無憂選 dropdown clicked", queue, loop)

        worryFreeOption = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//div[@id='mat-select-8-panel']//mat-option[.//span[contains(text(), '否')]]"))
        )
        driver.execute_script("arguments[0].click();", worryFreeOption)
        log_message("無憂選 否 clicked", queue, loop)

        if "美元" in form_data['currency']:
            currency_select_field = WebDriverWait(driver, TIMEOUT).until(
                EC.element_to_be_clickable((By.XPATH, "//label[contains(text(), '貨幣')]/following-sibling::mat-form-field//mat-select"))
            )
            driver.execute_script("arguments[0].click();", currency_select_field)
            log_message("貨幣 dropdown clicked", queue, loop)
            currency_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.element_to_be_clickable((By.XPATH, "//div[@id='mat-select-10-panel']//mat-option[.//span[contains(text(), '美元')]]"))
            )
            currency_option_field.click()
            log_message("美元 option clicked", queue, loop)

        nominalAmount_field = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//label[contains(text(), '名義金額')]/ancestor::qq-notional-amount//input"))
        )
        nominalAmount_field.clear()
        nominalAmount_field.send_keys(str(form_data['notionalAmount']))
        log_message("名義金額 field filled", queue, loop)

        if '每年' not in form_data['premiumPaymentMethod']:
            premiumPaymentMethod_select_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.ID, 'mat-select-value-13'))
            )
            premiumPaymentMethod_select_field.click()
            log_message("保費繳付方式 dropdown clicked", queue, loop)
            if '每半年' in form_data['premiumPaymentMethod']:
                numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//mat-option[contains(., "每半年")]'))
                )
                numberOfYear_option_field.click()
                log_message("保費繳付方式 每半年", queue, loop)
            elif '每季' in form_data['premiumPaymentMethod']:
                numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//mat-option[contains(., "每季")]'))
                )
                numberOfYear_option_field.click()
                log_message("保費繳付方式 每季", queue, loop)
            elif '每月' in form_data['premiumPaymentMethod']:
                numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//mat-option[contains(., "每月")]'))
                )
                numberOfYear_option_field.click()
                log_message("保費繳付方式 每月", queue, loop)

        supplimentary_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '/html/body/app-root/qq-base-structure/mat-drawer-container/mat-drawer-content/div/div/div/qq-left-tab/div/button[6]/span[2]/div'))
        )
        supplimentary_field.click()
        log_message("補充利益說明 page clicked", queue, loop)

        you_hope_field = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//label[contains(text(), '是')]"))
        )
        you_hope_field.click()
        log_message("提取說明 clicked", queue, loop)

        xpath = "//mat-label[span[text()='提取選項']]/following-sibling::mat-radio-group//label[span[text()='指定提取金額']]"
        try:
            element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", element)
            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            element.click()
            log_message("指定提取金額1 clicked", queue, loop)
        except ElementClickInterceptedException:
            log_message("Click intercepted, attempting JavaScript click...", queue, loop)
            driver.execute_script("arguments[0].click();", element)
            log_message("JS Click successful", queue, loop)

        withdraw_start_from = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//mat-label[span[text()='請選擇您的提取款項由']]/following-sibling::mat-radio-group//label[.//span[text()='保單年度']]"))
        )
        withdraw_start_from.click()
        log_message("保單年度 clicked", queue, loop)

        continue_button = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., '繼續')]"))
        )
        continue_button.click()
        log_message("繼續 clicked", queue, loop)

        WebDriverWait(driver, TIMEOUT).until(EC.staleness_of(continue_button))
        time.sleep(1)

        startYearNumber = str(int(number_of_years) + 1)
        base_num = None

        for start_id in ['14', '19']:
            input_id = f"mat-input-{start_id}"
            try:
                input_field = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.ID, input_id))
                )
                label = input_field.find_element(
                    By.XPATH,
                    ".//ancestor::mat-form-field/preceding-sibling::div[@class='mat-label-box']/mat-label"
                )
                if label.text.strip() == '由(保單年度)':
                    base_num = start_id
                    from_year_field = WebDriverWait(driver, 3).until(
                        EC.visibility_of_element_located((By.ID, f"{input_id}")))
                    from_year_field.send_keys(startYearNumber)
                    log_message(f"由(保單年度) Filled(14/19) {startYearNumber}", queue, loop)
                    break
            except TimeoutException:
                log_message(f"ID mat-input-{input_id} 未找到，尝试下一个...", queue, loop)
                continue

        if base_num is None:
            for i in range(13, 31):
                input_id = f"mat-input-{i}"
                try:
                    input_field = WebDriverWait(driver, 3).until(
                        EC.presence_of_element_located((By.ID, input_id))
                    )
                    label = input_field.find_element(
                        By.XPATH,
                        ".//ancestor::mat-form-field/preceding-sibling::div[@class='mat-label-box']/mat-label"
                    )
                    if label.text.strip() == '由(保單年度)':
                        base_num = i
                        from_year_field = WebDriverWait(driver, 3).until(
                            EC.visibility_of_element_located((By.ID, f"{input_id}")))
                        from_year_field.send_keys(startYearNumber)
                        log_message(f"由(保單年度) Filled {startYearNumber}", queue, loop)
                        break
                except Exception:
                    continue

        field_ids = {
            'takeout_year': f"mat-input-{int(base_num) + 1}",
            'every_year_amount': f"mat-input-{int(base_num) + 2}",
            'inflation': f"mat-input-{int(base_num) + 3}"
        }

        numberOfWithDrawYear = str(100 - int(number_of_years) - int(calculation_data['inputs'].get('age', '')))
        takeout_year_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.ID, field_ids['takeout_year'])))
        takeout_year_field.clear()
        takeout_year_field.send_keys(numberOfWithDrawYear)
        log_message(f"提取年期 filled with ID {field_ids['takeout_year']}", queue, loop)

        every_year_amount_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.ID, field_ids['every_year_amount'])))
        every_year_amount_field.clear()
        if not form_data['useInflation']:
            every_year_amount_field.send_keys('1000')
        else:
            premium = get_medical_premium(calculation_data['processedData'], startYearNumber)
            if "美元" in form_data['currency']:
                currency_rate = float(calculation_data['inputs'].get('currencyRate', ''))
                premium = round(premium / currency_rate, 0)
            every_year_amount_field.send_keys(str(int(premium)))
        log_message(f"每年提取金額 filled with ID {field_ids['every_year_amount']}", queue, loop)

        if form_data['useInflation']:
            inflation_rate = str(calculation_data['inputs'].get('inflationRate', ''))
            inflation_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.ID, field_ids['inflation']))
            )
            inflation_field.clear()
            inflation_field.send_keys(inflation_rate)
            log_message(f"通货膨胀率 filled with ID {field_ids['inflation']}", queue, loop)

        enter_button = WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located((By.XPATH, "//span[text()='加入']"))
        )
        driver.execute_script("arguments[0].click();", enter_button)
        log_message("加入 clicked, 請稍後... ", queue, loop)

        if not form_data['useInflation']:
            sorted_data = sorted(calculation_data['processedData'], key=lambda x: x['yearNumber'])
            start_index = next((i for i, item in enumerate(sorted_data) if item['yearNumber'] == int(startYearNumber)), None)
            if start_index is None:
                raise ValueError(f"Start year {startYearNumber} not found in processedData")
            end_index = start_index + int(numberOfWithDrawYear)
            withdrawal_data = sorted_data[start_index:end_index]
            currency_rate = float(calculation_data['inputs'].get('currencyRate', ''))
            for idx, entry in enumerate(withdrawal_data):
                premium = entry['medicalPremium']
                if "美元" in form_data['currency']:
                    premium = round(premium / currency_rate, 0)
                input_index = 28 + (idx * 5)
                xpath = f'//*[@id="mat-input-{input_index}"]'
                input_field = WebDriverWait(driver, 20).until(
                    EC.visibility_of_element_located((By.XPATH, xpath))
                )
                input_field.clear()
                input_field.send_keys(str(int(premium)))
                log_message(f"Filled year {entry['yearNumber']} ({premium}) in field {input_index}", queue, loop)

        result = perform_checkout(driver, form_data['notionalAmount'], form_data, queue, loop)
        if result["status"] == "success":
            driver.quit()
            sessions.pop(session_id, None)
            session_queues.pop(session_id, None)
        return result

    except Exception as e:
        log_message(f"Error in verify_otp_worker: {str(e)}", queue, loop)
        driver.quit()
        sessions.pop(session_id, None)
        session_queues.pop(session_id, None)
        raise

# Worker to retry with a new notional amount
def retry_notional_worker(session_id: str, new_notional_amount: str, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    session_data = sessions.get(session_id)
    if not session_data or "driver" not in session_data or "form_data" not in session_data:
        log_message("Invalid session ID", queue, loop)
        raise ValueError("Invalid session ID")
    driver = session_data["driver"]
    form_data = session_data["form_data"]

    try:
        basicPlan_field = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, '/html/body/app-root/qq-base-structure/mat-drawer-container/mat-drawer-content/div/div/div/qq-left-tab/div/button[2]/span[2]/div'))
        )
        basicPlan_field.click()
        log_message("基本計劃 page clicked", queue, loop)

        nominalAmount_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, "//label[contains(text(), '名義金額')]/ancestor::qq-notional-amount//input"))
        )
        nominalAmount_field.clear()
        nominalAmount_field.send_keys(new_notional_amount)
        log_message(f"New notional amount filled with {new_notional_amount}", queue, loop)

        result = perform_checkout(driver, new_notional_amount, form_data, queue, loop)
        if result["status"] == "success":
            driver.quit()
            sessions.pop(session_id, None)
            session_queues.pop(session_id, None)
        return result

    except Exception as e:
        log_message(f"Error in retry_notional_worker: {str(e)}", queue, loop)
        driver.quit()
        sessions.pop(session_id, None)
        session_queues.pop(session_id, None)
        raise

# Helper function to get medical premium
def get_medical_premium(processed_data, start_year_number):
    try:
        if not isinstance(processed_data, list):
            return None
        for entry in processed_data:
            if not isinstance(entry, dict):
                continue
            if entry.get('yearNumber') == int(start_year_number) and 'medicalPremium' in entry:
                return entry['medicalPremium']
        return None
    except Exception as e:
        return None

# FastAPI endpoints
@app.post("/login")
async def initiate_login(request: LoginRequest):
    session_id = str(uuid.uuid4())
    queue = asyncio.Queue()
    session_queues[session_id] = queue
    loop = asyncio.get_running_loop()
    try:
        await run_in_thread(
            selenium_worker,
            session_id,
            request.url,
            request.username,
            request.password,
            queue,
            loop
        )
        return {"session_id": session_id}
    except Exception as e:
        session_queues.pop(session_id, None)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/verify-otp")
async def verify_otp(request: OtpRequest):
    session_id = request.session_id
    queue = session_queues.get(session_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Session not found")
    loop = asyncio.get_running_loop()
    try:
        result = await run_in_thread(
            verify_otp_worker,
            session_id,
            request.otp,
            request.calculation_data.dict(),
            request.formData.dict(),
            queue,
            loop
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/retry-notional")
async def retry_notional(request: RetryRequest):
    session_id = request.session_id
    queue = session_queues.get(session_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Session not found")
    loop = asyncio.get_running_loop()
    try:
        result = await run_in_thread(
            retry_notional_worker,
            session_id,
            request.new_notional_amount,
            queue,
            loop
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# SSE endpoint for logs
@app.get("/logs/{session_id}")
async def stream_logs(session_id: str):
    queue = session_queues.get(session_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        while True:
            message = await queue.get()
            yield f"data: {message}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Data retrieval endpoint
class CalculationRequest(BaseModel):
    company: str
    planFileName: str
    age: int
    planOption: str
    numberOfYears: int

class OutputData(BaseModel):
    yearNumber: int
    age: int
    medicalPremium: float

@app.post("/getData", response_model=List[OutputData])
async def get_data(request: CalculationRequest):
    try:
        json_file = os.path.join(
            "plans",
            request.company,
            f"{request.planFileName}.json"
        )
        print("request.planFileName=", request.planFileName)
        print("request.planOption=", request.planOption)
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        max_age = 100
        max_years = max(max_age - request.age + 1, 1)
        result = []
        for year in range(1, max_years + 1):
            current_age = request.age + year - 1
            if str(current_age) not in data[str(request.planOption)]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Premium data not found for age {current_age}"
                )
            result.append({
                "yearNumber": year,
                "age": current_age,
                "medicalPremium": data[str(request.planOption)][str(current_age)]
            })
        return result
    except FileNotFoundError:
        logger.error(f"JSON file not found: {json_file}")
        raise HTTPException(status_code=404, detail="Plan data not found")
    except KeyError as e:
        logger.error(f"Invalid key: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Invalid parameters: {str(e)}")
    except json.JSONDecodeError:
        logger.error("JSON decode error")
        raise HTTPException(status_code=500, detail="Invalid JSON data")