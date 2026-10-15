FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY dashboard/ ./dashboard/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh
ENV HOST=0.0.0.0 PORT=5002
EXPOSE 5002
ENTRYPOINT ["./entrypoint.sh"]
