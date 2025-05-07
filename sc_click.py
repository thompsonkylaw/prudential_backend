import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, ElementClickInterceptedException

def sc_click(driver,log_func,xpath, logMessage):
    
    try:
        # log_func("Here 21")
        # Wait for the element to be visible and interactable
        you_hope_field_2 = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )
        # log_func("Here 22")
        # Scroll to the element
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", you_hope_field_2)
        # Wait again to ensure the element is still clickable after scrolling
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )
        # log_func("Here 23")
        # Optional: Small delay to allow any animations to settle
        time.sleep(1)  # Reduced from 5s to 1s to minimize unnecessary wait
        # Attempt to click the element
        you_hope_field_2.click()
        # log_func("Here 24")
        log_func(logMessage)

    except ElementClickInterceptedException:
        # log_func("Here 25")
        log_func("Click intercepted, attempting JavaScript click...")
        # Retry with JavaScript click
        driver.execute_script("arguments[0].click();", you_hope_field_2)
        # log_func("Here 26")
        log_func("JS Click successful")

    except TimeoutException:
        # log_func("Here 27")
        log_func("Element not found or not clickable within timeout")
        raise
    except Exception as e:
        # print(f"Here 38: Unexpected error - {str(e)}")
        log_func(f"Unexpected error during click: {str(e)}")
        raise