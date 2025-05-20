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
from urllib.parse import urljoin
from pdfminer.high_level import extract_text
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
import base64
from dotenv import load_dotenv
import shutil
import re
from selenium.webdriver.common.keys import Keys
from gs import fill_GS_form
from lv import fill_LV_form
from sc_click import sc_click
from sc_click_By_Name import sc_click_By_Name
import pytz

load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GROK2_API_KEY = os.getenv("GROK2_API_KEY")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment flag
IsProduction = False  # Set to True in production on Railway.app
UseGrok = False

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
class CalculationData(BaseModel):
    processedData: List[Dict]
    inputs: Dict
    totalAccumulatedMP: float

class CashValueInfo(BaseModel):
    age_1: int
    age_2: int
    age_1_cash_value: int
    age_2_cash_value: int
    annual_premium: int

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
    selectedAge1: int
    selectedAge2: int

class LoginRequest(BaseModel):
    session_id: str
    url: str
    username: str
    password: str
    calculation_data: CalculationData
    cashValueInfo: CashValueInfo
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

# New endpoint to initialize a session
@app.post("/init-session")
async def init_session():
    session_id = str(uuid.uuid4())
    queue = asyncio.Queue()
    session_queues[session_id] = queue
    return {"session_id": session_id}

# Selenium worker for initial login and form filling
def selenium_worker(session_id: str, url: str, username: str, password: str, calculation_data: Dict, cashValueInfo: Dict, formData: Dict, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    try:
        options = webdriver.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument("--disable-gpu")
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
        prefs = {
            "download.prompt_for_download": False,
            "plugins.always_open_pdf_externally": False,
        }
        options.add_experimental_option("prefs", prefs)

        if IsProduction:
            options.add_argument('--headless')
            driver = webdriver.Remote(command_executor='https://standalone-chrome-production-57ca.up.railway.app', options=options)
        else:
            driver = webdriver.Chrome(options=options)
        driver.maximize_window() 
        driver.get(url)
        
        def log_func(message):
            log_message(message, queue, loop)

        # Perform initial clicks
        sc_click(driver, log_func, '/html/body/div/header/div[1]/div[1]/div[1]/a[3]', '登入已點選')
        sc_click(driver, log_func, '/html/body/div/header/div[1]/div[5]/div/div[2]/div/a[2]', '理財顧問已點選')

        # Get all window handles and switch to the new tab
        all_handles = driver.window_handles
        new_tab_handle = all_handles[-1]
        driver.switch_to.window(new_tab_handle)

        # Enter username and password
        login_field = WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located((By.NAME, "username"))
        )
        login_field.send_keys(username)
        log_func("使用者名稱已發送")

        login_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.NAME, "password"))
        )
        login_field.send_keys(password)
        log_func("密碼已發送")

        # Submit the form
        sc_click(driver, log_func, '//*[@id="submit"]', '提交已點選')

        # Perform additional clicks
        sc_click(driver, log_func, '//*[@id="wrapper"]/div[2]/div/ul/li[1]/div/span', '營銷系統已點選')

        # Capture current window handles before the click that opens the new window
        current_handles = driver.window_handles

        # Perform the click that opens the new window
        sc_click(driver, log_func, '//*[@id="wrapper"]/div[2]/div/ul/li[1]/ul/li[11]/div/span', '建議書系統已點選')

        # Wait for the new window to open
        WebDriverWait(driver, TIMEOUT).until(
            lambda d: len(d.window_handles) > len(current_handles)
        )

        # Get all window handles again
        all_handles = driver.window_handles

        # Find the new window handle
        new_handle = [handle for handle in all_handles if handle not in current_handles][0]

        # Switch to the new window
        current_handles = driver.window_handles
        print(f"Current number of window handles: {len(current_handles)}")
        driver.switch_to.window(new_handle)
        current_handles = driver.window_handles
        print(f"Current number of window handles: {len(current_handles)}")
        # Wait for the button to be clickable and click it
        button = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "/html/body/div[2]/div[3]/div/div[3]/div[2]/div/div[1]/button"))
        )
        button.click()
        log_func("Button in new window clicked")
        driver.maximize_window() 

        # Fill out basic information
        sureName_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.NAME, "form.fla.surName"))
        )
        sureName_field.clear()
        sureName_field.send_keys(str(formData['surname']))
        log_func("英文姓氏 已填")

        givenName_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.NAME, "form.fla.firstName"))
        )
        givenName_field.clear()
        givenName_field.send_keys(str(formData['givenName']))
        log_func("英文名字 已填")

        if "Female" in formData['gender']:
            sc_click(driver, log_func, '//*[@id="root"]/div/div[3]/div[1]/div[12]/div/div/label[2]/span[2]', '女性已點選')
        else:
            sc_click(driver, log_func, '//*[@id="root"]/div/div[3]/div[1]/div[12]/div/div/label[1]/span[2]', '男性已點選')

        if formData['isSmoker']:
            sc_click(driver, log_func, '//*[@id="root"]/div/div[3]/div[1]/div[14]/div/div/label[2]/span[2]', '吸煙者已點選')
        else:    
            sc_click(driver, log_func, '//*[@id="root"]/div/div[3]/div[1]/div[14]/div/div/label[1]/span[2]', '非吸煙者已點選')
            
        age_field = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.NAME, "form.fla.anb"))
        )
        age_field.clear()
        age_value = calculation_data['inputs'].get('age', '')
        age_field.send_keys(str(age_value))  
        log_func("歲數已填")

        # Nationality dropdown
        dropdown_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "form.fla.nationality"))
        )
        try:
            dropdown_element.click() 
            log_func("成功點選")
        except:
            log_func("不成功點選")
            trigger_element = dropdown_element.find_element(By.XPATH, "./parent::div")
            trigger_element.click()
        options_container = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.CLASS_NAME, "MuiMenu-list"))
        )
        option = options_container.find_element(By.XPATH, ".//*[contains(text(), '香港')]")
        option.click()
        log_func("中國香港已點選")
        
        # Plan selection
        label = sc_click(driver, log_func, "//label[contains(text(), '請選擇')]", 'basicPlan 已點選')
        
        label = driver.find_element(By.XPATH, "//label[contains(text(), '請選擇')]")
        driver.execute_script("arguments[0].scrollIntoView(true);", label)
        select_id = label.get_attribute("for")
        select_element = driver.find_element(By.ID, select_id)
        select_element.click()
        log_func("1")
        
        options_list = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.XPATH, "//ul[@role='listbox']"))
        )
        basicPlan_ = str(formData['basicPlan'])
        log_func(f"basicPlan = {basicPlan_}")    
        
        if 'TRST' in basicPlan_:
            option = options_list.find_element(By.XPATH, ".//*[contains(text(), 'TRST')]")
            option.click()
            log_func("TRST已點選")    
        
        # Notional amount
        label = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.XPATH, "//label[text()='SA']"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", label)
        time.sleep(1)
        input_id = label.get_attribute("for")
        input_element = driver.find_element(By.ID, input_id)
        input_element.clear()
        input_element.send_keys(str(formData['notionalAmount']))
        log_func("notionalAmount filled")    
        
        sc_click(driver, log_func, "//input[@name='form.benefits.TRST.btpt']/parent::div/div[@role='combobox']", '保費繳付期 已點選')
        
        number_of_years = str(formData['premiumPaymentPeriod'])
        log_func(f"number_of_years = {number_of_years}")  
        useInflation = formData['useInflation']
        log_func(f"useInflation = {useInflation}")  
        processedData = calculation_data['processedData']
        
        if '5' in number_of_years:
            sc_click(driver, log_func, ".//li[@role='option' and contains(text(), '5')]", '5 @100')
        
        sc_click(driver, log_func, "//button[text()='完整表格加入金額']", '完整表格加入金額 已點選')
        ##############################################################################################################################
        time.sleep(3)
        startYearNumber = str(int(number_of_years) + 1)
        log_func(f"由(保單年度) = {startYearNumber}")
        numberOfWithDrawYear = str(100 - int(number_of_years) - int(calculation_data['inputs'].get('age', '')))
        
        log_func(f"提取期(年) = {numberOfWithDrawYear}")
        # if not formData['useInflation']:
        sorted_data = sorted(calculation_data['processedData'], key=lambda x: x['yearNumber'])
        start_index = next((i for i, item in enumerate(sorted_data) if item['yearNumber'] == int(startYearNumber)), None)
        if start_index is None:
            raise ValueError(f"Start year {startYearNumber} not found in processedData")
        end_index = start_index + int(numberOfWithDrawYear)
        withdrawal_data = sorted_data[start_index:end_index]
        currency_rate = float(calculation_data['inputs'].get('currencyRate', ''))

        for idx, entry in enumerate(withdrawal_data):
            premium = entry['medicalPremium']
            if "美元" in formData['currency']:
                premium = round(premium / currency_rate, 0)
            input_index = int(startYearNumber) + (idx)
            name = f"form.investments.{input_index}.partialSurrenders"
            input_element = driver.find_element(By.NAME, name)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", input_element)
            input_element.clear()
            input_element.send_keys(str(int(premium)))
            log_func(f"已填 翌年歲= {str(int(age_value) + input_index)} 保單年度終結=  {input_index}  現金提取={premium} in and input_index = {input_index}")
            time.sleep(0.2)
            
        time.sleep(1)
        
        # Perform checkout
        result = perform_checkout(driver, formData['notionalAmount'], formData, log_func, calculation_data, cashValueInfo, session_id)
        print("yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy")
        if result["status"] == "success":
            driver.quit()
            sessions.pop(session_id, None)
            session_queues.pop(session_id, None)
            return result
        elif result["status"] == "retry":
            sessions[session_id] = {"driver": driver, "form_data": formData, "calculation_data": calculation_data, "cashValueInfo": cashValueInfo}
            return {"status": "retry", "system_message": result["system_message"]}

    except Exception as e:
        log_func(f"Selenium error: {str(e)}")
        if session_id in sessions:
            driver = sessions.pop(session_id).get("driver")
            if driver:
                driver.quit()
        raise

# Helper function to perform checkout and capture PDF from network
def perform_checkout(driver, notional_amount: str, form_data: Dict, log_func, calculation_data: Dict, cash_value_info: Dict, session_id: str):
    age_value = calculation_data['inputs'].get('age', '')
    try:
        sc_click(driver, log_func, "//button[contains(text(), '預覽「補充說明」')]", '預覽「補充說明」 已點選')
        time.sleep(3)

        class EitherElementVisible:
            def __init__(self, system_message_locator, iframe_locator):
                self.system_message_locator = system_message_locator
                self.iframe_locator = iframe_locator

            def __call__(self, driver):
                try:
                    print("Checking for system message")
                    system_message = driver.find_element(*self.system_message_locator)
                    print(f"System message found with text: {system_message.text}")
                    return {"type": "system_message", "element": system_message}
                except NoSuchElementException:
                    print("System message not found")
                try:
                    print("Checking for iframe")
                    iframe = driver.find_element(*self.iframe_locator)
                    if iframe.is_displayed():
                        print("Iframe is displayed")
                        return {"type": "iframe", "element": iframe}
                    else:
                        print("Iframe not displayed")
                except NoSuchElementException:
                    print("Iframe not found")
                return False

        # system_message_locator = (By.XPATH, "//a[contains(text(), '保誠信守明天多元貨幣計劃 投保額過低')]")
        
        # system_message_locator = (By.XPATH, "//a[contains(normalize-space(.), '保誠信守明天多元貨幣計劃 投保額過低')]")
        system_message_locator = (By.XPATH, "//div[contains(@class, 'MuiAccordion-root') and .//p[contains(text(), '錯誤訊息')]]//div[contains(@class, 'MuiAccordionDetails-root')]//a")
        iframe_locator = (By.CSS_SELECTOR, "div.MuiGrid2-root iframe")

        result = WebDriverWait(driver, 30).until(
            EitherElementVisible(system_message_locator, iframe_locator)
        )
        
        cleaned_amount = notional_amount.replace(',', '')
        integer_part = cleaned_amount.split('.')[0]
        formatted_amount = f"{int(integer_part):,}"
        
        basicPlan_ = str(form_data['basicPlan'])
        if result["type"] == "system_message":
            # print("4")
            system_message = result["element"].text
            error_message = system_message.split(":")[1].strip()
            log_func(f"系統信息: {error_message}")
            # cleaned_amount = notional_amount.replace(',', '')
            # integer_part = cleaned_amount.split('.')[0]
            # formatted_amount = f"{int(integer_part):,}"
            # print("5")
            return {
                "status": "retry",
                "system_message": f"{system_message}\n 對上一次輸入的名義金額為${formatted_amount}",

            }
        elif result["type"] == "iframe":
            iframe = result["element"]
            log_func("PDF 正在加載...")
            # Extract the PDF URL from the iframe's src attribute
            pdf_relative_url = iframe.get_attribute("src").split('#')[0]
            current_url = driver.current_url
            pdf_full_url = urljoin(current_url, pdf_relative_url)
            
            # Get the current cookies from the Selenium driver
            cookies = driver.get_cookies()
            session = requests.Session()
            for cookie in cookies:
                session.cookies.set(cookie['name'], cookie['value'])
            headers = {"Referer": current_url}
            response = session.get(pdf_full_url, headers=headers)
            response.raise_for_status()
            pdf_bytes = response.content
            pdf_file = io.BytesIO(pdf_bytes)
            text = extract_text(pdf_file)
            tz_gmt8 = pytz.timezone("Asia/Shanghai")
            timestamp = datetime.now(tz_gmt8).strftime("%Y%m%d%H%M")
            filename = f"{basicPlan_}_{timestamp}"
            print(text)
            pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
            pattern = r"由於所有保單值已被提取，本保單將於第\d+保單年度終結時終止。"
            matches = re.findall(pattern, text)
            for match in matches:
                year_match = re.search(r'第(\d+)保單年度', match)
                if year_match:
                    number = int(year_match.group(1))  
                    ending_age = int(age_value) + number
                return {
                    "status": "retry",
                    "system_message": f"由於所有保單值已被提取，本保單將於第{number}保單年度(第{ending_age}歲)終結時終止 \n 對上一次輸入的名義金額為${formatted_amount}",

                }
            
            sc_click(driver, log_func, "//div[div/h5='保費及徵費 -']//button", '核對 已點選')
            #################################################################################################
            
            annual_div = WebDriverWait(driver, 10).until(
                EC.visibility_of_element_located((By.XPATH, "//p[normalize-space(text())='每年']/.."))
            )
            # annual_div = driver.find_element(By.XPATH, "//p[normalize-space(text())='每年']/..")
            annual_text = annual_div.text

            # Extract USD and HKD amounts for annual
            annual_usd = re.search(r'美元\s*([\d,]+\.\d{2})', annual_text).group(1)
            print("annual_usd",annual_usd)
            annual_hkd = re.search(r'港元\s*([\d,]+\.\d{2})', annual_text).group(1)
            print("annual_hkd",annual_hkd)
            # Locate the div containing the monthly ("每月") information
            monthly_div = driver.find_element(By.XPATH, "//p[normalize-space(text())='每月']/..")
            monthly_text = monthly_div.text

            # Extract USD and HKD amounts for monthly
            monthly_usd = re.search(r'美元\s*([\d,]+\.\d{2})', monthly_text).group(1)
            print("monthly_usd",monthly_usd)
            monthly_hkd = re.search(r'港元\s*([\d,]+\.\d{2})', monthly_text).group(1)
            print("monthly_hkd",monthly_hkd)
            
            sc_click(driver, log_func, "//button[text()='製作建議書']", '製作建議書 已點選')
            sc_click(driver, log_func, "//button[text()='檢視建議書']", '檢視建議書 已點選')
            
            
            original_window = driver.current_window_handle
            WebDriverWait(driver, 10).until(lambda d: len(d.window_handles) > 1)
            all_handles = driver.window_handles
            print("abc")
            pdf_base64 = None
            pdf_window_handle = None
            for handle in all_handles:
                if handle != original_window:
                    driver.switch_to.window(handle)
                    print("handle=",handle)
                    current_url = driver.current_url
                    print("current_url",current_url)
                    if current_url.endswith(".pdf"):
                        pdf_window_handle = handle
                        # Extract PDF using requests
                        cookies = driver.get_cookies()
                        session = requests.Session()
                        for cookie in cookies:
                            session.cookies.set(cookie['name'], cookie['value'])
                        headers = {"Referer": current_url}
                        response = session.get(current_url, headers=headers)
                        response.raise_for_status()
                        pdf_bytes = response.content
                        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
                        log_func("Proposal PDF extracted and encoded successfully")
                        break
            

            
            

            
            return {
                "status": "success",
                "pdf_base64": pdf_base64,
                "filename": filename + ".pdf"
                # data as needed
            }

    except TimeoutException as e:
        log_func(f"Error: {str(e)}")
        raise Exception(str(e))
    except Exception as e:
        log_func(f"Unexpected error: {str(e)}")
        raise

# Worker to retry with a new notional amount
def retry_notional_worker(session_id: str, new_notional_amount: str, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    session_data = sessions.get(session_id)
    if not session_data or "driver" not in session_data or "form_data" not in session_data:
        log_message("Invalid session ID", queue, loop)
        raise ValueError("Invalid session ID")
    driver = session_data["driver"]
    form_data = session_data["form_data"]
    calculation_data = session_data["calculation_data"]
    cash_value_info = session_data["cashValueInfo"]

    def log_func(message):
        log_message(message, queue, loop)

    try:
        # Notional amount
        label = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.XPATH, "//label[text()='SA']"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", label)
        
        input_id = label.get_attribute("for")
        input_element = driver.find_element(By.ID, input_id)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", input_element)
        
        time.sleep(2)
       
        # input_element.clear()
        input_element.click()

    # Select all text with Ctrl+A and delete it
        input_element.send_keys(Keys.CONTROL + 'a')
        input_element.send_keys(Keys.DELETE)
        print(new_notional_amount)
        
        
        input_element.send_keys(str(new_notional_amount))
        log_func("notionalAmount filled")    
        time.sleep(1)
        result = perform_checkout(driver, new_notional_amount, form_data, log_func, calculation_data, cash_value_info, session_id)
        print("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        
        if result["status"] == "success":
            driver.quit()
            sessions.pop(session_id, None)
            session_queues.pop(session_id, None)
        return result

    except Exception as e:
        log_func(f"Error in retry_notional_worker: {str(e)}")
        driver.quit()
        sessions.pop(session_id, None)
        session_queues.pop(session_id, None)
        raise

# Modified /login endpoint
@app.post("/login")
async def initiate_login(request: LoginRequest):
    session_id = request.session_id
    queue = session_queues.get(session_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Session not found")
    loop = asyncio.get_running_loop()
    try:
        def log_func(message):
            log_message(message, queue, loop)
        result = await run_in_thread(
            selenium_worker,
            session_id,
            request.url,
            request.username,
            request.password,
            request.calculation_data.dict(),
            request.cashValueInfo.dict(),
            request.formData.dict(),
            queue,
            loop
        )
        if result["status"] == "retry":
            return {"status": "retry", "system_message": result["system_message"], "session_id": session_id}
        else:
            return result
    except Exception as e:
        session_queues.pop(session_id, None)
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
            loop,
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