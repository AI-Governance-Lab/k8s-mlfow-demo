FROM python:3.10-slim
RUN pip install --no-cache-dir "mlflow==3.3.2" psycopg2-binary boto3 gunicorn
CMD ["mlflow", "server", "--host=0.0.0.0", "--port=5000"]