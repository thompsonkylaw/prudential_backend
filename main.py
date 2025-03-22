# uvicorn main:app --reload
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

from typing import List, Dict

app = FastAPI()
executor = ThreadPoolExecutor(max_workers=5)  # Control concurrency

# Configure CORS
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

class OtpRequest(BaseModel):
    session_id: str
    otp: str

# Session storage (use Redis in production)
sessions = {}
TIMEOUT = 30

async def run_in_thread(func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, func, *args)

def selenium_worker(session_id: str, url: str, username: str, password: str):
    try:
        options = webdriver.ChromeOptions()
        # options.add_argument('--headless')
        
        # Run Chrome in headless mode
        # options.add_argument('--headless')
        
        options.add_argument('--no-sandbox')         # Bypass OS security model (required in some server environments)
        options.add_argument('--disable-dev-shm-usage')  # Overcome limited shared memory issues
        options.add_argument("--disable-gpu")
        
        driver = webdriver.Chrome(options=options)
         
        # driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()),options=options)
        # driver = webdriver.Remote(command_executor='http://212.192.15.100:45678',options=options) #machine1
        # driver = webdriver.Remote(command_executor='https://standalone-chrome-production-57ca.up.railway.app',options=options) #machine1 ok
        
        # driver = webdriver.Remote(command_executor='https://standalone-chrome-production-c446.up.railway.app',options=options) #machine1
       
        # driver = webdriver.Remote(command_executor='http://10.250.17.56:4444',options=options) #machine1
        
        
 
        
        driver.get(url)
        # Login phase
        # WebDriverWait(driver, TIMEOUT).until(
        #     EC.presence_of_element_located((By.ID, 'user'))
        # ).send_keys(username)
        login_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.ID, "user"))
        )
        login_field.send_keys(username)
        print("username sent")
        
        driver.find_element(By.ID, 'password').send_keys(password)
        print("password sent")
        
        #click submit
        driver.find_element(By.XPATH, '//*[@id="form"]/button').click()
        print("button clicked")
        # Trigger OTP
        
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
        # sessions.pop(session_id).quit()########################################
    except Exception as e:
        logging.error(f"Selenium error: {str(e)}")
        if session_id in sessions:
            sessions.pop(session_id).quit()
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

def verify_otp_worker(session_id: str, otp: str):
    driver = sessions.get(session_id)
    if not driver:
        raise ValueError("Invalid session ID")
    
    try:
        # Enter OTP
        for i in range(6):
            # Construct the XPath for each pin field (pin_0, pin_1, etc.)
            pin_xpath = f'//*[@id="pin_{i}"]'
            
            # Wait for the pin field to be visible
            otp_pin = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, pin_xpath))
            )
            
            # Send the corresponding digit to the field
            otp_pin.send_keys(otp[i])
            print(f"otp_pin_{otp[i]} entered")
        
        time.sleep(1)
        # otp_pin_0 = WebDriverWait(driver, TIMEOUT).until(
        #     EC.visibility_of_element_located((By.XPATH, '//*[@id="pin_0"]'))
        # )
        
        # otp_pin_0.send_keys(otp)
        # print("otp_pin_0 entered")
        
        driver.find_element(By.XPATH, '//*[@id="verify"]/div[2]/button[1]').click()
        print("otp_continual_button clicked")
        
        # Final verification
        # WebDriverWait(driver, TIMEOUT).until(
        #     EC.presence_of_element_located((By.XPATH, '//*[contains(text(), "制作建議書")]'))
        # )
        
        
        proposal_button = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[.//span[text()='製作建議書']]")
            )
        )
        proposal_button.click()
        print("Proposal button clicked")
        
        english_name_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-input-1"]'))
        )
        
        print("english_name_field showed")
        
        time.sleep(5)
        
       
        # Cleanup
        driver.quit()
        sessions.pop(session_id)
    except Exception as e:
        driver.quit()
        sessions.pop(session_id, None)
        raise

@app.post("/verify-otp")
async def verify_otp(request: OtpRequest):
    try:
        await run_in_thread(
            verify_otp_worker,
            request.session_id,
            request.otp
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
        # Construct file path
        json_file = os.path.join(
            "plans",
            request.year,
            "manulife",
            f"{request.plan}_{request.year}.json"
        )

        # Load JSON data
        with open(json_file, 'r') as f:
            data = json.load(f)

        # Calculate maximum years until age 100
        max_age = 100
        max_years = max(max_age - request.age + 1, 1)  # Ensure at least 1 year
        
        # Generate output data
        result = []
        for year in range(1, max_years + 1):
            current_age = request.age + year - 1
            
            # Validate age exists in data
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
        logging.error(f"Invalid JSON format in file: {json_file}")
        raise HTTPException(status_code=500, detail="Invalid data format")
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")    
