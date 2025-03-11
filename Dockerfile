# Use the Selenium Standalone Chrome image
FROM selenium/standalone-chrome:latest

# Set Chrome to run in headless mode (optional but recommended)
ENV SE_CHROME_ARGS="--headless=new"

# Expose the Selenium server port
EXPOSE 4444