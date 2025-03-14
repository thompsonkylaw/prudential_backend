from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from pydantic import BaseModel
import uuid
import logging
import time
from contextlib import asynccontextmanager
from typing import Dict
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Application lifespan management
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code
    logger.info("Starting application")
    yield
    # Shutdown code
    logger.info("Shutting down application")
    for session_id in list(sessions.keys()):
        try:
            sessions[session_id].quit()
        except Exception as e:
            logger.error(f"Error quitting session {session_id}: {str(e)}")
        del sessions[session_id]

app = FastAPI(lifespan=lifespan)

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

# Session storage
sessions: Dict[str, webdriver.Chrome] = {}
SESSION_TIMEOUT = 300  # 5 minutes

def create_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    
    # Production-ready Chrome configuration
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--single-process")
    options.add_argument("--remote-debugging-port=9222")
    
    # For Docker compatibility
    if os.getenv("DOCKER_ENV"):
        options.binary_location = "/usr/bin/google-chrome"
        return webdriver.Chrome(
            options=options,
            service=webdriver.ChromeService(executable_path="/usr/bin/chromedriver")
        )
    
    return webdriver.Chrome(options=options)

def perform_login_actions(driver: webdriver.Chrome, username: str, password: str):
    logger.info("Starting login sequence")
    
    # Login fields
    WebDriverWait(driver, 30).until(
        EC.visibility_of_element_located((By.ID, "user"))
    ).send_keys(username)
    
    driver.find_element(By.ID, 'password').send_keys(password)
    driver.find_element(By.XPATH, '//*[@id="form"]/button').click()
    
    # OTP trigger
    WebDriverWait(driver, 30).until(
        EC.visibility_of_element_located((By.XPATH, '//*[@id="otp"]/div[1]/div[1]/input'))
    ).click()
    
    WebDriverWait(driver, 30).until(
        EC.element_to_be_clickable((By.XPATH, '//*[@id="otp"]/div[2]/button[1]'))
    ).click()

def perform_otp_verification(driver: webdriver.Chrome, otp: str):
    logger.info("Starting OTP verification")
    
    # OTP input
    for i in range(6):
        pin_xpath = f'//*[@id="pin_{i}"]'
        WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.XPATH, pin_xpath))
        ).send_keys(otp[i])
    
    # Final submission
    WebDriverWait(driver, 30).until(
        EC.element_to_be_clickable((By.XPATH, '//*[@id="verify"]/div[2]/button[1]'))
    ).click()
    
    # Wait for success state
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.XPATH, "//button[.//span[text()='製作建議書']]"))
    ).click()
    
    # Validate final page load
    WebDriverWait(driver, 30).until(
        EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-input-1"]'))
    )

@app.post("/login")
async def initiate_login(request: LoginRequest):
    session_id = str(uuid.uuid4())
    driver = None
    
    try:
        driver = create_driver()
        driver.get(request.url)
        
        perform_login_actions(driver, request.username, request.password)
        
        sessions[session_id] = {
            "driver": driver,
            "expires": time.time() + SESSION_TIMEOUT
        }
        
        return {"session_id": session_id}
        
    except Exception as e:
        logger.error(f"Login failed: {str(e)}")
        if driver:
            driver.quit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login process failed"
        )

@app.post("/verify-otp")
async def verify_otp(request: OtpRequest):
    session_data = sessions.get(request.session_id)
    
    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or expired"
        )
    
    if time.time() > session_data["expires"]:
        session_data["driver"].quit()
        del sessions[request.session_id]
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail="Session expired"
        )
    
    try:
        perform_otp_verification(session_data["driver"], request.otp)
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"OTP verification failed: {str(e)}")
        session_data["driver"].quit()
        del sessions[request.session_id]
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OTP verification failed"
        )
    finally:
        # Cleanup even if successful
        session_data["driver"].quit()
        del sessions[request.session_id]

# Background cleanup task
async def session_cleanup():
    while True:
        now = time.time()
        expired_sessions = [
            session_id for session_id, data in sessions.items()
            if data["expires"] < now
        ]
        
        for session_id in expired_sessions:
            try:
                sessions[session_id]["driver"].quit()
                del sessions[session_id]
                logger.info(f"Cleaned up expired session: {session_id}")
            except Exception as e:
                logger.error(f"Error cleaning session {session_id}: {str(e)}")
        
        await asyncio.sleep(60)  # Run cleanup every minute

# Start cleanup task on application startup
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(session_cleanup())