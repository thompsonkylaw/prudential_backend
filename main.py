from fastapi import FastAPI, HTTPException, BackgroundTasks
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
import time
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import json
import os
from typing import List, Dict, Optional

app = FastAPI()
executor = ThreadPoolExecutor(max_workers=5)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class LoginRequest(BaseModel):
    url: str
    username: str
    password: str

class CalculationData(BaseModel):
    processedData: List[Dict]
    inputs: Dict
    totalAccumulatedMP: float


class OtpRequest(BaseModel):
    session_id: str
    otp: str
    calculation_data: Optional[CalculationData] = None

sessions = {}
TIMEOUT = 60

async def run_in_thread(func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, func, *args)

def selenium_worker(session_id: str, url: str, username: str, password: str):
    try:
        options = webdriver.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument("--disable-gpu")
        
        driver = webdriver.Chrome(options=options)
        driver.get(url)
        
        login_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.ID, "user"))
        )
        login_field.send_keys(username)
        print("username sent")
        
        driver.find_element(By.ID, 'password').send_keys(password)
        print("password sent")
        
        driver.find_element(By.XPATH, '//*[@id="form"]/button').click()
        print("button clicked")
        
        mailOpion = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//*[@id="otp"]/div[1]/div[1]/input'))
        )
        mailOpion.click()
        print("mailOpion clicked")
        
        sendOtpRequestButton = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//*[@id="otp"]/div[2]/button[1]'))
        )
        sendOtpRequestButton.click()
        print("sendOtpRequestButton clicked")
        
        sessions[session_id] = driver
    except Exception as e:
        logging.error(f"Selenium error: {str(e)}")
        if session_id in sessions:
            sessions.pop(session_id).quit()
        raise

def verify_otp_worker(session_id: str, otp: str, calculation_data: Optional[Dict] = None):
    driver = sessions.get(session_id)
    if not driver:
        raise ValueError("Invalid session ID")
    
    try:
        # Enter OTP
        for i in range(6):
            pin_xpath = f'//*[@id="pin_{i}"]'
            otp_pin = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, pin_xpath))
            )
            otp_pin.send_keys(otp[i])
            print(f"otp_pin_{otp[i]} entered")
        
        time.sleep(1)
        driver.find_element(By.XPATH, '//*[@id="verify"]/div[2]/button[1]').click()
        print("otp_continual_button clicked")
        
        proposal_button = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[.//span[text()='製作建議書']]")
            )
        )
        proposal_button.click()
        print("Proposal button clicked")
        
        # english_name_field = WebDriverWait(driver, TIMEOUT).until(
        #     EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-input-1"]'))
        # )
        # print("english_name_field showed")
        
        # Fill form with calculation data if provided
        if calculation_data:
            print("Filling form with calculation data...")
            inputs = calculation_data.get('inputs', {})
            processed_data = calculation_data.get('processedData', [])
            total_mp = calculation_data.get('totalAccumulatedMP', 0)
            
            # Example of filling form fields (adjust selectors as needed)
            try:
                
                # Fill age
                sureName_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-input-1"]'))
                )
                sureName_field.clear()
                # sureName_field.send_keys(str(inputs.get('age', '')))
                sureName_field.send_keys('VIP')
                print("sureName_field field filled")
                
                # Fill age
                name_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-input-2"]'))
                )
                name_field.clear()
                # name_field.send_keys(str(inputs.get('age', '')))
                name_field.send_keys('VIP2')
                print("name_field field filled")
                
                # Fill age
                age_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-input-5"]'))
                )
                age_field.clear()
                age_field.send_keys(str(inputs.get('age', '')))
              
                print("Age field filled")
                
                # Fill age
                basicPlan_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '/html/body/app-root/qq-base-structure/mat-drawer-container/mat-drawer-content/div/div/div/qq-left-tab/div/button[2]/span[2]/div'))
                )
                basicPlan_field.click()
                print("基本計劃page clicked")
                
                
              
                basicPlan_select_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-select-value-5"]'))
                )
                basicPlan_select_field.click()
                print("基本計劃 Select clicked")
                
                basicPlan_option_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-option-14"]/span'))
                )
                basicPlan_option_field.click()
                print("基本計劃 GS option clicked")
                
                numberOfYear_select_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-select-value-7"]'))
                )
                numberOfYear_select_field.click()
                print("保費繳付期 Select clicked")
                
                print("str(inputs.get('numberOfYears', ''))",str(inputs.get('numberOfYears', '')))
                if str(inputs.get('numberOfYears', '')) == '3':
                    numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                        EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-option-46"]'))
                        
                    )
                    numberOfYear_option_field.click()
                    print("保費繳付期 3 year clicked")
                elif str(inputs.get('numberOfYears', '')) == '5':
                    numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                        EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-option-47"]'))
                    )
                    numberOfYear_option_field.click()
                    print("保費繳付期 5 year clicked")
                elif str(inputs.get('numberOfYears', '')) == '10':
                    numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                        EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-option-48"]'))
                    )
                    numberOfYear_option_field.click()
                    print("保費繳付期 10 year clicked")
                elif str(inputs.get('numberOfYears', '')) == '15':
                    numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                        
                        EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-option-49"]'))
                        
                        
                    )
                    numberOfYear_option_field.click()
                    print("保費繳付期 15 year clicked")        
                    
                currency_select_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-select-value-11"]'))
                )
                currency_select_field.click()
                print("貨幣 Select clicked")
                
                currency_option_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-option-53"]'))
                )
                currency_option_field.click()
                print("貨幣  option clicked")
                    
               
                nominalAmount_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-input-6"]'))
                )
                nominalAmount_field.send_keys("20000")
                
                print("nominalAmount_field clicked")
                
               
                
                
                # 
                # //*[@id="mat-option-626"]
                # //*[@id="mat-option-626"]
                # //*[@id="mat-option-626"]
                
                
                # Fill plan type
                plan_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-option-5"]'))
                )
                plan_field.click()
                
                print("Plan GS click")
                
                # Fill total premium
                premium_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.XPATH, '//*[@id="premium-input"]'))
                )
                premium_field.clear()
                premium_field.send_keys(str(total_mp))
                print("Premium field filled")
                
            except Exception as e:
                print(f"Error filling form: {str(e)}")
        
        time.sleep(5)
        
        # Cleanup
        driver.quit()
        sessions.pop(session_id)
    except Exception as e:
        driver.quit()
        sessions.pop(session_id, None)
        raise

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
        await run_in_thread(
            verify_otp_worker,
            request.session_id,
            request.otp,
            request.calculation_data.dict() if request.calculation_data else None
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        logging.error(f"JSON file not found: {json_file}")
        raise HTTPException(status_code=404, detail="Plan data not found")
    except KeyError as e:
        logging.error(f"Invalid key: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Invalid parameters: {str(e)}")
    except json.JSONDecodeError:
        logging.error