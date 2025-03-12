ARG PORT=443

FROM cypress/browsers:latest

# 更新 apt 並安裝必要工具
RUN apt-get update && apt-get install -y python3 python3-pip

# 確保 Python 和 Pip 可用
RUN python3 --version && pip3 --version

# 設置 Python 使用者安裝路徑
ENV PATH /root/.local/bin:${PATH}

# 複製 requirements.txt 並安裝 Python 依賴
COPY requirements.txt . 
RUN pip3 install --no-cache-dir -r requirements.txt

# 複製應用程式文件
COPY . .

# 啟動應用
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
