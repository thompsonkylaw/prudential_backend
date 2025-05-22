import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, ElementClickInterceptedException
from sc_click import sc_click


def fill_TRST_form(driver, formData, calculation_data, log_func, TIMEOUT=120):
    time.sleep(4)
    options_list = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.XPATH, "//ul[@role='listbox']"))
        )
    # driver.execute_script("arguments[0].scrollIntoView(true);", options_list)
    # driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", options_list)
    option = options_list.find_element(By.XPATH, ".//*[contains(text(), 'TRST')]")
    # option = WebDriverWait(driver, 10).until(
    #          EC.element_to_be_clickable((By.XPATH, ".//*[contains(text(), 'TRST')]"))
    #     )
    option.click()
    log_func("TRST 已點選")    
    
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
    log_func("名義金額 已填")    
    
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
    age_value = calculation_data['inputs'].get('age', '')
    for idx, entry in enumerate(withdrawal_data):
        premium = entry['medicalPremium']
        if "美元" in formData['currency']:
            premium = round(premium / currency_rate, 0)
        input_index = int(startYearNumber) + (idx)
        name = f"form.investments.{input_index}.partialSurrenders"
        try:
            input_element = WebDriverWait(driver, 10).until(
                EC.visibility_of_element_located((By.NAME, name))
            )
        except TimeoutException:
            log_func(f"Timeout waiting for element with name {name} after 10 seconds")
            raise
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", input_element)
        input_element.clear()
        input_element.send_keys(str(int(premium)))
        log_func(f"已填 翌年歲= {str(int(age_value) + input_index)} 保單年度終結=  {input_index}  現金提取=${premium} in and input_index = {input_index}")
        time.sleep(0.2)
        
    time.sleep(1)