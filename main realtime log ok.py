from fastapi import FastAPI, HTTPException, BackgroundTasks, Response
from fastapi.middleware.cors import CORSMiddleware
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from pydantic import BaseModel
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
from queue import Queue
import time
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import json
import os
from typing import List, Dict, Optional
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from datetime import datetime
from selenium.common.exceptions import ElementClickInterceptedException
import tempfile
from zoneinfo import ZoneInfo
from sse_starlette.sse import EventSourceResponse

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Queue to store log messages for streaming
log_queue = Queue()

# Custom logging handler to put messages into the queue
class QueueHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        log_queue.put(msg)

handler = QueueHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

# Environment flag
IsProduction = False

# Initialize FastAPI app
app = FastAPI()
executor = ThreadPoolExecutor(max_workers=5)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models
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

class CalculationRequest(BaseModel):
    year: str
    plan: str
    age: int
    deductible: int
    numberOfYears: int

class OutputData(BaseModel):
    yearNumber: int
    age: int
    medicalPremium: float

# Global session storage and timeout
sessions = {}
TIMEOUT = 120

# Helper function to run synchronous tasks in a thread
async def run_in_thread(func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, func, *args)

# SSE endpoint to stream log messages
@app.get("/stream-logs")
async def stream_logs():
    async def event_generator():
        while True:
            if not log_queue.empty():
                message = log_queue.get()
                yield {
                    "event": "message",
                    "data": message
                }
            await asyncio.sleep(0.1)

    return EventSourceResponse(event_generator())

# Selenium worker for initial login
def selenium_worker(session_id: str, url: str, username: str, password: str):
    try:
        options = webdriver.ChromeOptions()
        if IsProduction:
            options.add_argument('--headless')
            temp_dir = tempfile.mkdtemp()
            prefs = {
                "download.default_directory": temp_dir,
                "download.prompt_for_download": False,
                "plugins.always_open_pdf_externally": False
            }
            options.add_experimental_option("prefs", prefs)
        
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument("--disable-gpu")
        
        if IsProduction:
            driver = webdriver.Remote(command_executor='https://standalone-chrome-production-57ca.up.railway.app', options=options)
        else:
            driver = webdriver.Chrome(options=options)   
             
        driver.get(url)
        
        login_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.ID, "user"))
        )
        login_field.send_keys(username)
        logger.info("username sent")
        
        driver.find_element(By.ID, 'password').send_keys(password)
        logger.info("password sent")
        
        driver.find_element(By.XPATH, '//*[@id="form"]/button').click()
        logger.info("login button clicked")
        
        mailOption = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, "//label[contains(., '已登記的電郵地址')]"))
        )
        mailOption.click()
        logger.info("mailOption clicked")
        
        sendOtpRequestButton = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//*[@id="otp"]/div[2]/button[1]'))
        )
        sendOtpRequestButton.click()
        logger.info("sendOtpRequestButton clicked")
        
        sessions[session_id] = {"driver": driver}
    except Exception as e:
        logger.error(f"Selenium error: {str(e)}")
        if session_id in sessions:
            sessions.pop(session_id)["driver"].quit()
        raise

# Helper function to perform checkout
def perform_checkout(driver, notional_amount: str, form_data: Dict):
    policy_field = WebDriverWait(driver, 30).until(
        EC.element_to_be_clickable((By.XPATH, '/html/body/app-root/qq-base-structure/mat-drawer-container/mat-drawer-content/div/div/div/qq-left-tab/div/button[7]/span[2]/div'))
    )
    policy_field.click()
    logger.info("保費摘要 clicked")

    class EitherElementLocated:
        def __init__(self, locator1, locator2):
            self.locator1 = locator1
            self.locator2 = locator2

        def __call__(self, driver):
            try:
                element = driver.find_element(*self.locator1)
                if element.is_displayed():
                    return {"type": "system_message", "element": element}
            except NoSuchElementException:
                pass
            try:
                element = driver.find_element(*self.locator2)
                if element.is_displayed():
                    return {"type": "view_button", "element": element}
            except NoSuchElementException:
                pass
            return False

    system_message_locator = (By.XPATH, "//div[@class='control-message']//li")
    view_button_locator = (By.XPATH, "/html/body/app-root/qq-base-structure/mat-drawer-container/mat-drawer-content/div/div/div/div/div/qq-premium-summary/div/div[3]/button/span[2]")

    try:
        result = WebDriverWait(driver, 30).until(
            EitherElementLocated(system_message_locator, view_button_locator)
        )

        if result["type"] == "system_message":
            system_message = result["element"].text
            logger.info(f"系統信息: {system_message}")
            return {
                "status": " asparagus",
                "system_message": f"{system_message}\n 對上一次輸入的名義金額為${notional_amount}"
            }
        elif result["type"] == "view_button":
            view_button = result["element"]
            view_button.click()
            logger.info("檢視建議書 clicked")

            save_input_field = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//input[@matinput and @maxlength='80']"))
            )
            tz_gmt8 = ZoneInfo("Asia/Shanghai")
            timestamp = datetime.now(tz_gmt8).strftime("%Y%m%d%H%M")
            filename = f"宏摯傳承保障計劃_{timestamp}"
            save_input_field.clear()
            save_input_field.send_keys(filename)

            save_button = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, "//mat-dialog-container//div[@class='dialog-buttons']/button[contains(., '儲存')]"))
            )
            try:
                save_button.click()
                logger.info("儲存1 button successfully clicked")
            except:
                ActionChains(driver).move_to_element(save_button).pause(0.5).click().perform()
                logger.info("儲存2 button successfully clicked")
                    
            if str(form_data['proposalLanguage']) == "zh":
                proposal_language_radio = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@value='zh']/ancestor::div[contains(@class, 'mdc-radio')]"))
                )
                proposal_language_radio.click()
                logger.info("proposalLanguage_radio = zh")
            elif str(form_data['proposalLanguage']) == "sc":
                proposal_language_radio = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@value='sc']/ancestor::div[contains(@class, 'mdc-radio')]"))
                )
                proposal_language_radio.click()
                logger.info("proposalLanguage_radio = sc")
            else:
                proposal_language_radio = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@value='zh']/ancestor::div[contains(@class, 'mdc-radio')]"))
                )
                proposal_language_radio.click()
                logger.info("proposalLanguage_radio = zh (default)")

            label = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//label[.//div[text()='所有年期']]"))
            )
            label.click()
            logger.info("所有年期 checked")

            print_button = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, "//cpos-button[.//span[contains(., '列印建議書')]]//button[contains(@class, 'agent-btn')]"))
            )
            try:
                print_button.click()
                logger.info("列印建議書1 button clicked successfully")
            except:
                ActionChains(driver).move_to_element_with_offset(print_button, 5, 5).pause(0.3).click().perform()
                logger.info("列印建議書2 button clicked successfully")

            temp_dir = tempfile.mkdtemp()
            pdf_path = os.path.join(temp_dir, f"{filename}.pdf")
            time.sleep(15)
            return {"status": "success", "pdf_link": f"/{pdf_path}"}
    except TimeoutException:
        raise Exception("Neither system message nor view button found within 30 seconds")

# Worker to verify OTP and fill form
def verify_otp_worker(session_id: str, otp: str, calculation_data: Dict, form_data: Dict):
    session_data = sessions.get(session_id)
    if not session_data or "driver" not in session_data:
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
            logger.info(f"otp_pin_{otp[i]} entered")
        
        otp_continual_button = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="verify"]/div[2]/button[1]'))
        )
        otp_continual_button.click()
        logger.info("繼續 clicked")
        
        proposal_button = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//button[.//span[text()='製作建議書']]"))
        )
        proposal_button.click()
        logger.info("Proposal button clicked")
        
        if form_data['isCorporateCustomer']:
            isCorporateCustomer_field = WebDriverWait(driver, TIMEOUT).until(
                EC.presence_of_element_located((By.ID, "mat-mdc-checkbox-1-input"))
            )
            isCorporateCustomer_field.click()
            logger.info("Clicked isCorporateCustomer checkbox")
        
        if form_data['isPolicyHolder']:
            isPolicyHolder_field = WebDriverWait(driver, TIMEOUT).until(
                EC.presence_of_element_located((By.ID, 'mat-radio-5-input'))
            )
            isPolicyHolder_field.click()
            logger.info("isPolicyHolder is true")
        else:
            isPolicyHolder_field = WebDriverWait(driver, TIMEOUT).until(
                EC.presence_of_element_located((By.ID, 'mat-radio-6-input'))
            )
            isPolicyHolder_field.click()
            logger.info("isPolicyHolder is false")
                
        sureName_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//div[label[contains(text(), "英文姓氏")]]//input'))
        )
        sureName_field.clear()
        sureName_field.send_keys(str(form_data['surname']))
        logger.info("Surname field filled")
        
        givenName_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//div[label[contains(text(), "英文名字")]]//input'))
        )
        givenName_field.clear()
        givenName_field.send_keys(str(form_data['givenName']))
        logger.info("Given name field filled")
        
        if form_data['chineseName']:
            chineseName_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, '//div[label[contains(text(), "中文姓名")]]//input'))
            )
            chineseName_field.clear()
            chineseName_field.send_keys(str(form_data['chineseName']))
            logger.info("chineseName_field filled")
        
        age_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//div[label[contains(text(), "投保年齡")]]//input'))
        )
        age_field.clear()
        age_field.send_keys(str(form_data['insuranceAge']))
        logger.info("insuranceAge field filled")
        
        if "Female" in form_data['gender']:
            gender_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, "//mat-radio-button[@value='Female']"))
            )
            gender_field.click()
            logger.info("gender_field Female clicked")
        
        if form_data['isSmoker']:
            isSmoker_field = WebDriverWait(driver, TIMEOUT).until(
                EC.element_to_be_clickable((By.XPATH, "//mat-radio-button[@value='Yes']"))
            )
            isSmoker_field.click()
            logger.info("isSmoker_field yes clicked")
                
        basicPlan_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '/html/body/app-root/qq-base-structure/mat-drawer-container/mat-drawer-content/div/div/div/qq-left-tab/div/button[2]/span[2]/div'))
        )
        basicPlan_field.click()
        logger.info("基本計劃page clicked")
            
        basicPlan_select_field = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//label[contains(text(), '基本計劃')]/following-sibling::mat-form-field//mat-select"))
        )
        driver.execute_script("arguments[0].click();", basicPlan_select_field)
        logger.info("基本計劃 Dropdown clicked")
        
        if 'GS' in str(form_data['basicPlan']):
            basicPlan_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.element_to_be_clickable((By.XPATH, "//div[@id='mat-select-4-panel']//mat-option[.//span[contains(text(), '(GS)')]]"))
            )
            basicPlan_option_field.click()
            logger.info("基本計劃 GS option clicked")
        
        numberOfYear_select_field = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//label[contains(text(), '保費繳付期')]/following-sibling::mat-form-field//mat-select"))
        )
        driver.execute_script("arguments[0].click();", numberOfYear_select_field)
        logger.info("保費繳付期 Dropdown clicked")
        
        number_of_years = str(calculation_data['inputs'].get('numberOfYears', ''))
        if '3' in number_of_years:
            numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, '//mat-option[contains(., "3")]'))
            )
            numberOfYear_option_field.click()
            logger.info("保費繳付期 3 year clicked")
        elif '15' in number_of_years:
            numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, '//mat-option[contains(., "15")]'))
            )
            numberOfYear_option_field.click()
            logger.info("保費繳付期 15 year clicked")
        elif '10' in number_of_years:
            numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, '//mat-option[contains(., "10")]'))
            )
            numberOfYear_option_field.click()
            logger.info("保費繳付期 10 year clicked")
        elif '5' in number_of_years:
            numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, '//mat-option[contains(., "5")]'))
            )
            numberOfYear_option_field.click()
            logger.info("保費繳付期 5 year clicked")
        
        worryFreeSelection = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//label[contains(text(), '無憂選')]/following-sibling::mat-form-field//mat-select"))
        )
        driver.execute_script("arguments[0].click();", worryFreeSelection)
        logger.info("無憂選 dropdown clicked")
        
        worryFreeOption = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//div[@id='mat-select-8-panel']//mat-option[.//span[contains(text(), '否')]]"))
        )
        driver.execute_script("arguments[0].click();", worryFreeOption)
        logger.info("無憂選 否 clicked")
        
        if "美元" in form_data['currency']:
            currency_select_field = WebDriverWait(driver, TIMEOUT).until(
                EC.element_to_be_clickable((By.XPATH, "//label[contains(text(), '貨幣')]/following-sibling::mat-form-field//mat-select"))
            )
            driver.execute_script("arguments[0].click();", currency_select_field)
            logger.info("貨幣 dropdown clicked")
            currency_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.element_to_be_clickable((By.XPATH, "//div[@id='mat-select-10-panel']//mat-option[.//span[contains(text(), '美元')]]"))
            )
            currency_option_field.click()
            logger.info("美元 option clicked")
        
        nominalAmount_field = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//label[contains(text(), '名義金額')]/ancestor::qq-notional-amount//input"))
        )
        nominalAmount_field.clear()
        nominalAmount_field.send_keys(str(form_data['notionalAmount']))
        logger.info("名義金額 field filled")
        
        if '每年' not in form_data['premiumPaymentMethod']:
            premiumPaymentMethod_select_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.ID, 'mat-select-value-13'))
            )
            premiumPaymentMethod_select_field.click()
            logger.info("保費繳付方式 dropdown clicked")
            if '每半年' in form_data['premiumPaymentMethod']:
                numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//mat-option[contains(., "每半年")]'))
                )
                numberOfYear_option_field.click()
                logger.info("保費繳付方式 每半年")
            elif '每季' in form_data['premiumPaymentMethod']:
                numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//mat-option[contains(., "每季")]'))
                )
                numberOfYear_option_field.click()
                logger.info("保費繳付方式 每季")
            elif '每月' in form_data['premiumPaymentMethod']:
                numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//mat-option[contains(., "每月")]'))
                )
                numberOfYear_option_field.click()
                logger.info("保費繳付方式 每月")
        
        supplimentary_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '/html/body/app-root/qq-base-structure/mat-drawer-container/mat-drawer-content/div/div/div/qq-left-tab/div/button[6]/span[2]/div'))
        )
        supplimentary_field.click()
        logger.info("補充利益說明 page clicked")
        
        you_hope_field = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//label[contains(text(), '是')]"))
        )
        you_hope_field.click()
        logger.info("提取說明 clicked")
            
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
            logger.info("指定提取金額1 clicked")
        except ElementClickInterceptedException:
            logger.info("Click intercepted, attempting JavaScript click...")
            driver.execute_script("arguments[0].click();", element)
            logger.info("指定提取金額2 clicked")
        
        withdraw_start_from = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//mat-label[span[text()='請選擇您的提取款項由']]/following-sibling::mat-radio-group//label[.//span[text()='保單年度']]"))
        )
        withdraw_start_from.click()
        logger.info("保單年度 clicked")
        
        continue_button = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., '繼續')]"))
        )
        continue_button.click()
        logger.info("繼續 clicked")
        
        startYearNumber = str(int(number_of_years) + 1)
        base_num = None
        for start_id in ['14', '19']:
            try:
                from_year_field = WebDriverWait(driver, 3).until(
                    EC.visibility_of_element_located((By.ID, f"mat-input-{start_id}")))
                base_num = int(start_id)
                logger.info(f"成功定位到基础ID: mat-input-{start_id}")
                break
            except TimeoutException:
                logger.info(f"ID mat-input-{start_id} 未找到，尝试下一个...")
                continue

        if base_num is None:
            raise Exception("无法定位由(保單年度)的输入框")

        from_year_field.clear()
        from_year_field.send_keys(startYearNumber)
        logger.info("由(保單年度) filled")

        field_ids = {
            'takeout_year': f"mat-input-{base_num + 1}",
            'every_year_amount': f"mat-input-{base_num + 2}",
            'inflation': f"mat-input-{base_num + 3}"
        }

        # numberOfWithDrawYear = str(100 - int(number_of_years) - int(calculation_data['inputs'].get('age', '')))
        numberOfWithDrawYear = str(100 - int(number_of_years) - int(form_data['insuranceAge']))
        takeout_year_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.ID, field_ids['takeout_year'])))
        takeout_year_field.clear()
        takeout_year_field.send_keys(numberOfWithDrawYear)
        logger.info(f"提取年期 filled with ID {field_ids['takeout_year']}")

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
        logger.info(f"每年提取金額 filled with ID {field_ids['every_year_amount']}")

        if form_data['useInflation']:
            inflation_rate = str(calculation_data['inputs'].get('inflationRate', ''))
            inflation_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.ID, field_ids['inflation']))
            )
            inflation_field.clear()
            inflation_field.send_keys(inflation_rate)
            logger.info(f"通货膨胀率 filled with ID {field_ids['inflation']}")

        enter_button = WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located((By.XPATH, "//span[text()='加入']"))
        )
        driver.execute_script("arguments[0].click();", enter_button)
        logger.info("加入 clicked")

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
                input_field = WebDriverWait(driver, 10).until(
                    EC.visibility_of_element_located((By.XPATH, xpath))
                )
                input_field.clear()
                input_field.send_keys(str(int(premium)))
                logger.info(f"Filled year {entry['yearNumber']} ({premium}) in field {input_index}")

        result = perform_checkout(driver, form_data['notionalAmount'], form_data)
        if result["status"] == "success":
            driver.quit()
            sessions.pop(session_id, None)
        return result

    except Exception as e:
        driver.quit()
        sessions.pop(session_id, None)
        raise

# Worker to retry with a new notional amount
def retry_notional_worker(session_id: str, new_notional_amount: str):
    session_data = sessions.get(session_id)
    if not session_data or "driver" not in session_data or "form_data" not in session_data:
        raise ValueError("Invalid session ID")
    driver = session_data["driver"]
    form_data = session_data["form_data"]
    
    try:
        basicPlan_field = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, '/html/body/app-root/qq-base-structure/mat-drawer-container/mat-drawer-content/div/div/div/qq-left-tab/div/button[2]/span[2]/div'))
        )
        basicPlan_field.click()
        logger.info("基本計劃 page clicked")

        nominalAmount_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, "//label[contains(text(), '名義金額')]/ancestor::qq-notional-amount//input"))
        )
        nominalAmount_field.clear()
        nominalAmount_field.send_keys(new_notional_amount)
        logger.info("New notional amount filled")

        result = perform_checkout(driver, new_notional_amount, form_data)
        if result["status"] == "success":
            driver.quit()
            sessions.pop(session_id, None)
        return result

    except Exception as e:
        driver.quit()
        sessions.pop(session_id, None)
        raise

# Helper function to get medical premium
def get_medical_premium(processed_data, start_year_number):
    try:
        if not isinstance(processed_data, list):
            logger.info(f"Expected list, got {type(processed_data)}")
            return None
        for entry in processed_data:
            if not isinstance(entry, dict):
                continue
            if entry.get('yearNumber') == int(start_year_number) and 'medicalPremium' in entry:
                return entry['medicalPremium']
        logger.info(f"No matching entry found for year {start_year_number}")
        return None
    except Exception as e:
        logger.info(f"Processing error: {str(e)}")
        return None

# FastAPI endpoints
@app.post("/login")
async def initiate_login(request: LoginRequest):
    session_id = str(uuid.uuid4())
    try:
        await run_in_thread(
            selenium_worker,
            session_id,
            request.url,
            request.username,
            request.password
        )
        return {"session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/verify-otp")
async def verify_otp(request: OtpRequest):
    try:
        result = await run_in_thread(
            verify_otp_worker,
            request.session_id,
            request.otp,
            request.calculation_data.dict(),
            request.formData.dict()
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/retry-notional")
async def retry_notional(request: RetryRequest):
    try:
        result = await run_in_thread(
            retry_notional_worker,
            request.session_id,
            request.new_notional_amount
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/getData", response_model=List[OutputData])
async def get_data(request: CalculationRequest):
    try:
        json_file = os.path.join(
            "plans",
            request.year,
            "manulife",
            f"{request.plan}_{request.year}.json"
        )
        with open(json_file, 'r') as f:
            data = json.load(f)
        max_age = 100
        max_years = max(max_age - request.age + 1, 1)
        result = []
        for year in range(1, max_years + 1):
            current_age = request.age + year - 1
            if str(current_age) not in data[str(request.deductible)]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Premium data not found for age {current_age}"
                )
            result.append({
                "yearNumber": year,
                "age": current_age,
                "medicalPremium": data[str(request.deductible)][str(current_age)]
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