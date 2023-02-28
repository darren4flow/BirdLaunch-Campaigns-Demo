FROM python:3.11.1-slim-buster

WORKDIR /app

COPY requirements.txt requirements.txt

COPY script.py script.py

RUN pip3 install -r requirements.txt

ENTRYPOINT [ "python3", "script.py"]
