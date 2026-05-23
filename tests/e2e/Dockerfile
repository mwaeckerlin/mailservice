FROM python:3.12-alpine
RUN apk add --no-cache busybox-extras  # provides telnet for connectivity checks
WORKDIR /tests
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
