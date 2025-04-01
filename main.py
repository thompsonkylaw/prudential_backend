working2
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
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from datetime import datetime

app = FastAPI()
executor = ThreadPoolExecutor(max_workers=5)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define Pydantic models for the payload
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
    dob: str
    gender: str
    isSmoker: bool
    basicPlan: str
    currency: str
    notionalAmount: str
    premiumPaymentMethod: str
    useInflation: bool

class OtpRequest(BaseModel):
    session_id: str
    otp: str
    calculation_data: CalculationData
    formData: FormData

sessions = {}
TIMEOUT = 300

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
        
        mailOption = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//*[@id="otp"]/div[1]/div[1]/input'))
        )
        mailOption.click()
        print("mailOption clicked")
        
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

def verify_otp_worker(session_id: str, otp: str, calculation_data: Dict, form_data: Dict):
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
        
        driver.find_element(By.XPATH, '//*[@id="verify"]/div[2]/button[1]').click()
        print("otp_continual_button clicked")
        
        proposal_button = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[.//span[text()='製作建議書']]")
            )
        )
        proposal_button.click()
        print("Proposal button clicked")
        
        # isCorporateCustomer    
        print("['isCorporateCustomer']", form_data['isCorporateCustomer'])
        if form_data['isCorporateCustomer'] is True:
            try:
                isCorporateCustomer_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.presence_of_element_located((By.ID, "mat-mdc-checkbox-1-input"))
                )
                isCorporateCustomer_field.click()
                print("Clicked isCorporateCustomer checkbox")
            except Exception as e:
                print(f"Error clicking checkbox: {e}")
        else:
            print("isCorporateCustomer is false")    
            # isPolicyHolder
            print("['isPolicyHolder']", form_data['isPolicyHolder'])    
            if form_data['isPolicyHolder'] is True:
                isPolicyHolder_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.presence_of_element_located((By.ID, 'mat-radio-5-input'))
                )
                isPolicyHolder_field.click()    
                print("isPolicyHolder is true")
            else:
                isPolicyHolder_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.presence_of_element_located((By.ID, 'mat-radio-6-input'))
                )
                isPolicyHolder_field.click()    
                print("isPolicyHolder is false")
               
        # time.sleep(5)
        # Fill surname
        sureName_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-input-1"]'))
        )
        sureName_field.clear()
        sureName_field.send_keys(str(form_data['surname']))
        print("Surname field filled")
        
        # Fill given name
        givenName_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-input-2"]'))
        )
        givenName_field.clear()
        givenName_field.send_keys(str(form_data['givenName']))
        print("Given givenName field filled")
        
        # chineseName
        if form_data['chineseName']:
            chineseName_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-input-3"]'))
            )
            chineseName_field.clear()
            chineseName_field.send_keys(str(form_data['chineseName']))
            print("chineseName_field filled")
        
        # dob    
        if form_data['dob']:
            dob_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-input-4"]'))
            )
            dob_field.clear()
            dob_field.send_keys(str(form_data['dob']))
            print("dob_field field filled")

        # age
        age_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-input-5"]'))
        )
        age_field.clear()
        age_field.send_keys(str(calculation_data['inputs'].get('age', '')))
        print("Age field filled")        
        
        # gender    
        print("form_data['gender']", form_data['gender'])
        if "Female" in form_data['gender']:
            gender_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.ID, 'mat-radio-3'))
            )
            gender_field.click()
            print("gender_field Female clicked")    
        
        # isSmoker   
        print("form_data['isSmoker']", form_data['isSmoker'])
        if form_data['isSmoker'] is True:
            isSmoker_field = WebDriverWait(driver, TIMEOUT).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//mat-radio-button[.//input[@id='mat-radio-11-input']]"))
            )
            isSmoker_field.click()
            print("isSmoker_field yes clicked")
        else:
            print("isSmoker_field no clicked")        
        
        # 基本計劃
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
        
        # basicPlan
        print("form_data['basicPlan']", form_data['basicPlan'])
        if 'GS' in str(form_data['basicPlan']):
            basicPlan_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-option-14"]/span'))
            )
            basicPlan_option_field.click()
            print("基本計劃 GS option clicked")
        time.sleep(1)
        #保費繳付期
        numberOfYear_select_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-select-value-7"]'))
        )
        numberOfYear_select_field.click()
        print("保費繳付期 Select clicked")
        
        number_of_years = str(calculation_data['inputs'].get('numberOfYears', ''))
        print("number_of_years=", number_of_years)
        time.sleep(1)
        if '3' in number_of_years:
            numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located(
                    (By.XPATH, '//mat-option[contains(., "3")]')
                )
            )
            numberOfYear_option_field.click()
            print("保費繳付期 3 year clicked")
        elif '15' in number_of_years:
            numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located(
                    (By.XPATH, '//mat-option[contains(., "15")]')
                )
            )
            numberOfYear_option_field.click()
            print("保費繳付期 15 year clicked")
        elif '10' in number_of_years:
            numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located(
                    (By.XPATH, '//mat-option[contains(., "10")]')
                )
            )
            numberOfYear_option_field.click()
            print("保費繳付期 10 year clicked")
        elif '5' in number_of_years:
            numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located(
                    (By.XPATH, '//mat-option[contains(., "5")]')
                )
            )
            numberOfYear_option_field.click()
            print("保費繳付期 5 year clicked")
            
        # time.sleep(1)
        # 無憂選
        worryFreeSelection = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.ID, 'mat-select-value-9'))
        )
        worryFreeSelection.click()
        print("無憂選 Selection clicked")
        time.sleep(1)
        
        worryFreeOption = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-option-51"]'))
        )
        worryFreeOption.click()
        print("無憂選 Selection clicked")
        
        # currency
        print("form_data['currency']=", form_data['currency'])
        if "美元" in form_data['currency']:
            currency_select_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-select-value-11"]'))
            )
            currency_select_field.click()
            print("貨幣 Select clicked")
            
            time.sleep(1)
            
            currency_option_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-option-53"]'))
            )
            currency_option_field.click()
            print("美元 option clicked")
        
        # time.sleep(1)
        
        # 名義金額notional amount
        print("form_data['notionalAmount']=", form_data['notionalAmount'])
        nominalAmount_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '//*[@id="mat-input-6"]'))
        )
        nominalAmount_field.send_keys(str(form_data['notionalAmount']))
        print("Notional amount field filled")
        
        print("form_data['premiumPaymentMethod']=", form_data['premiumPaymentMethod'])
       
        if '每年' not in form_data['premiumPaymentMethod']:       
            premiumPaymentMethod_select_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.ID, 'mat-select-value-13'))
            )
            premiumPaymentMethod_select_field.click()
            print("保費繳付方式 Select clicked")
            
            time.sleep(1)
            
            if '每半年' in form_data['premiumPaymentMethod']:
                numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located(
                        (By.XPATH, '//mat-option[contains(., "每半年")]')
                    )
                )
                numberOfYear_option_field.click()
                print("保費繳付方式 每半年")
            elif '每季' in form_data['premiumPaymentMethod']:
                numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located(
                        (By.XPATH, '//mat-option[contains(., "每季")]')
                    )
                )
                numberOfYear_option_field.click()
                print("保費繳付方式 每季")
            elif '每月' in form_data['premiumPaymentMethod']:
                numberOfYear_option_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located(
                        (By.XPATH, '//mat-option[contains(., "每月")]')
                    )
                )
                numberOfYear_option_field.click()
                print("保費繳付方式 每月")
        
        # supplimentary_field
        supplimentary_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '/html/body/app-root/qq-base-structure/mat-drawer-container/mat-drawer-content/div/div/div/qq-left-tab/div/button[6]/span[2]/div'))
        )
        supplimentary_field.click()
        print("補充利益說明 page clicked")
        
        # 提取說明   
        you_hope_field = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//input[@value='yes']/ancestor::div[contains(@class, 'mdc-radio')]")
            )
        )
        you_hope_field.click()        
        print("提取說明 clicked")
        
        time.sleep(1)
        
        # 指定提取金額
        withdrawalPeriod_option_field = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//input[@value='fixedamount']/ancestor::div[contains(@class, 'mdc-radio')]")
            )
        )
        withdrawalPeriod_option_field.click()
        print("指定提取金額 clicked")
        
        # 保單年度
        withdraw_start_from = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//input[@value='year']/ancestor::div[contains(@class, 'mdc-radio')]")
            )
        )
        withdraw_start_from.click()
        print("保單年度 clicked")
        
        # 繼續
        continue_button = WebDriverWait(driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., '繼續')]")))
        continue_button.click()  
        print("繼續 clicked")  
        
        time.sleep(1)
        
        # 由(保單年度)
        startYearNumber = str(int(number_of_years) + 1)
        base_num = None

        # 尝试可能的ID列表
        for start_id in ['14', '19']:
            try:
                from_year_field = WebDriverWait(driver, 3).until(
                    EC.visibility_of_element_located((By.ID, f"mat-input-{start_id}")))
                base_num = int(start_id)
                print(f"成功定位到基础ID: mat-input-{start_id}")
                break
            except TimeoutException:
                print(f"ID mat-input-{start_id} 未找到，尝试下一个...")
                continue

        if base_num is None:
            raise Exception("无法定位由(保單年度)的输入框")

        # 处理第一个输入字段
        try:
            from_year_field.clear()
            from_year_field.send_keys(startYearNumber)
            print("由(保單年度) filled")
        except Exception as e:
            print(f"输入保單年度时出错: {str(e)}")
            raise

        # 生成后续字段的ID模板
        field_ids = {
            'takeout_year': f"mat-input-{base_num + 1}",
            'every_year_amount': f"mat-input-{base_num + 2}",
            'inflation': f"mat-input-{base_num + 3}"
        }

        # 提取年期
        try:
            numberOfWithDrawYear = str(100 - int(number_of_years) - int(calculation_data['inputs'].get('age', '')))
            takeout_year_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.ID, field_ids['takeout_year'])))
            takeout_year_field.clear()
            takeout_year_field.send_keys(numberOfWithDrawYear)
            print(f"提取年期 filled with ID {field_ids['takeout_year']}")
        except TimeoutException:
            raise Exception(f"找不到提取年期字段 ID: {field_ids['takeout_year']}")
        except Exception as e:
            print(f"提取年期字段操作失败: {str(e)}")
            raise

        # 每年提取金额
        try:
            every_year_amount_field = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.ID, field_ids['every_year_amount'])))
            every_year_amount_field.clear()
            
            if not form_data['useInflation']:
                every_year_amount_field.send_keys('1000')
            else:
                premium = get_medical_premium(calculation_data['processedData'], startYearNumber)
                print("Inflation premium=", premium)
                if "美元" in form_data['currency']:
                    currency_rate = float(calculation_data['inputs'].get('currencyRate', ''))
                    premium = round(premium / currency_rate, 0)
                    print("Use USD")
                else:
                    print("Use HKD") 
                every_year_amount_field.send_keys(str(int(premium)))
                    
            print(f"每年提取金額 filled with ID {field_ids['every_year_amount']}")
        except TimeoutException:
            raise Exception(f"找不到每年提取金额字段 ID: {field_ids['every_year_amount']}")
        except Exception as e:
            print(f"每年提取金额字段操作失败: {str(e)}")
            raise

        # 处理通货膨胀率字段
        if form_data['useInflation']:
            try:
                inflation_rate = str(calculation_data['inputs'].get('inflationRate', ''))
                inflation_field = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.ID, field_ids['inflation']))
                )
                inflation_field.clear()
                inflation_field.send_keys(inflation_rate)
                print(f"通货膨胀率 filled with ID {field_ids['inflation']}")
            except TimeoutException:
                raise Exception(f"找不到通货膨胀率字段 ID: {field_ids['inflation']}")
            except Exception as e:
                print(f"通货膨胀率字段操作失败: {str(e)}")
                raise
        
        # 加入
        enter_button = WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located((By.XPATH, "//span[text()='加入']"))
        )
        driver.execute_script("arguments[0].click();", enter_button)
        print("加入 clicked")  
        
        print("calculation_data['inputs'].get('currencyRate', '')=", str(calculation_data['inputs'].get('currencyRate', '')))
        print("\n--- Processed Data ---")
        for entry in calculation_data.get('processedData', []):
            print(json.dumps(entry, indent=2))
        print("----------------------\n")
        
        currency_rate = float(calculation_data['inputs'].get('currencyRate', ''))
        startYearNumber = int(startYearNumber)
        numberOfWithDrawYear = int(numberOfWithDrawYear)
        
        print("currency_rate", currency_rate)
        print("startYearNumber", startYearNumber)
        print("numberOfWithDrawYear", numberOfWithDrawYear)
        print("useInflation=", form_data['useInflation'])
        
        if not form_data['useInflation']:
            sorted_data = sorted(calculation_data['processedData'], 
                            key=lambda x: x['yearNumber'])
            start_index = next((i for i, item in enumerate(sorted_data) 
                            if item['yearNumber'] == startYearNumber), None)
            
            if start_index is None:
                raise ValueError(f"Start year {startYearNumber} not found in processedData")

            end_index = start_index + numberOfWithDrawYear
            withdrawal_data = sorted_data[start_index:end_index]

            for idx, entry in enumerate(withdrawal_data):
                premium = entry['medicalPremium']
                if "美元" in form_data['currency']:
                    premium = round(premium / currency_rate, 0)
                    print("Use USD")
                else:
                    print("Use HKD")    

                input_index = 28 + (idx * 5)
                xpath = f'//*[@id="mat-input-{input_index}"]'
                input_field = WebDriverWait(driver, 10).until(
                    EC.visibility_of_element_located((By.XPATH, xpath))
                )
                
                input_field.clear()
                input_field.send_keys(str(int(premium)))
                print(f"Filled year {entry['yearNumber']} ({premium}) in field {input_index}")
        
        time.sleep(1)    
        policy_field = WebDriverWait(driver, TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, '/html/body/app-root/qq-base-structure/mat-drawer-container/mat-drawer-content/div/div/div/qq-left-tab/div/button[7]/span[2]/div'))
        )
        policy_field.click()
        print("保費摘要 clicked")
        ###################################################
        ###################################################
        time.sleep(1)
        # Retrieve system message
        try:
            system_message = WebDriverWait(driver, TIMEOUT).until(
                EC.visibility_of_element_located((By.XPATH, "//div[@class='control-message']//li"))
            ).text
            print(f"System Message: {system_message}")
        except Exception as e:
            print(f"Error retrieving system message: {str(e)}")
            system_message = "No message found"
        
        #檢視建議書
        view_button = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable(
            (By.XPATH, "/html/body/app-root/qq-base-structure/mat-drawer-container/mat-drawer-content/div/div/div/div/div/qq-premium-summary/div/div[3]/button/span[2]")
            )
        )
        view_button.click()  
        print(f"檢視建議書 checked")
        
        #save file name
        save_input_field = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@matinput and @maxlength='80']"))
        )
        # Generate timestamp in yyyymmddhhmmss format
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        
        # Create dynamic filename
        filename = f"宏摯傳承保障計劃_{timestamp}"
        # Clear existing text and input new value
        save_input_field.clear()
        save_input_field.send_keys(filename)
       
        #儲存
        # First: Wait for the dialog container to be fully rendered
        WebDriverWait(driver, 15).until(
            EC.visibility_of_element_located((By.XPATH, "//mat-dialog-container[contains(@class, 'cdk-dialog-container')]"))
        )

        # Second: Use a precise XPath targeting the specific button
        save_button = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, 
                "//mat-dialog-container//div[@class='dialog-buttons']/button[contains(., '儲存')]"))
        )

        # Third: Use a combination of Actions and JavaScript click
        try:
            # Normal click attempt
            save_button.click()
            print("儲存1 button successfully clicked")
        except:
            # Fallback 1: Actions chain with precise offset
            ActionChains(driver).move_to_element(save_button).pause(0.5).click().perform()
            
            # Fallback 2: JavaScript click
            driver.execute_script("arguments[0].dispatchEvent(new MouseEvent('click', {bubbles: true}));", save_button)

            print("儲存2 button successfully clicked")
        
        
        #Simple Chinese   
        SimpleChinese_radio = WebDriverWait(driver, 10).until(
            # EC.element_to_be_clickable((By.XPATH, "//input[@type='radio' and @value='sc']"))
            EC.element_to_be_clickable((By.XPATH, "//input[@value='sc']/ancestor::div[contains(@class, 'mdc-radio')]")
                    ))
        SimpleChinese_radio.click()
        print(f"SimpleChinese_radio checked")
        
        #所有年期
        label = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//label[.//div[text()='所有年期']]"))
        )
        label.click()
        print(f"所有年期 checked")
                        
        #print
        # Target the specific print button using its unique context
        print_button = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, 
                "//cpos-button[.//span[contains(., '列印建議書')]]"
                "//button[contains(@class, 'agent-btn')]"))
        )

        # Triple-layer interaction to ensure click success
        try:
            # Normal click attempt
            print_button.click()
            print("列印建議書1 button clicked successfully")
        except:
            # Action chain with precise positioning
            ActionChains(driver)\
                .move_to_element_with_offset(print_button, 5, 5)\
                .pause(0.3)\
                .click()\
                .perform()
            
            # JavaScript fallback
            driver.execute_script("arguments[0].dispatchEvent(new MouseEvent('click', {bubbles: true}));", print_button)

            print("列印建議書2 button clicked successfully")
        
        
        # Cleanup
        driver.quit()
        sessions.pop(session_id)
        
        # return ""  # Return the system message
        return system_message  # Return the system message
    
    except Exception as e:
        driver.quit()
        sessions.pop(session_id, None)
        raise

def get_medical_premium(processed_data, start_year_number):
    try:
        print(f"[Debug] Type: {type(processed_data)}, Length: {len(processed_data) if isinstance(processed_data, list) else 'N/A'}")
        if not isinstance(processed_data, list):
            print(f"Expected list, got {type(processed_data)}")
            return None

        for entry in processed_data:
            if not isinstance(entry, dict):
                continue
            if (entry.get('yearNumber') == int(start_year_number) 
                and 'medicalPremium' in entry):
                return entry['medicalPremium']

        print(f"No matching entry found for year {start_year_number}")
        return None
    except Exception as e:
        print(f"Processing error: {str(e)}")
        return None
    
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
        system_message = await run_in_thread(
            verify_otp_worker,
            request.session_id,
            request.otp,
            request.calculation_data.dict(),
            request.formData.dict()
        )
        return {"status": "success", "system_message": system_message}
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
        logging.error("JSON decode error")
        raise HTTPException(status_code=500, detail="Invalid JSON data")