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
        driver = webdriver.Chrome(options=options)
        
        driver.get(url)
        # Login phase
        WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located((By.ID, 'username'))
        ).send_keys(username)
        driver.find_element(By.ID, 'password').send_keys(password)
        driver.find_element(By.ID, 'login-btn').click()
        
        # Trigger OTP
        WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.ID, 'send-otp'))
        ).click()
        
        sessions[session_id] = driver
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
        WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located((By.ID, 'otp'))
        ).send_keys(otp)
        driver.find_element(By.ID, 'verify-otp').click()
        
        # Final verification
        WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located((By.XPATH, '//*[contains(text(), "制作建議書")]'))
        )
        
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