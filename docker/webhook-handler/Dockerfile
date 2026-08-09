FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY docker/webhook-handler/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY automation/response_engine/ /app/response_engine/
COPY cmdb/ /app/cmdb/

CMD [ "gunicorn", "--bind", "0.0.0.0:8000", "response_engine.webhook_handler:app" ]
