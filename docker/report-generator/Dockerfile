FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY docker/report-generator/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Keep the package structure intact so the module can be executed as:
#   python -m automation.report_generator.report_generator
COPY automation ./automation

# Report generation consumes the shared CMDB.
COPY cmdb ./cmdb

CMD ["python", "-m", "automation.report_generator.report_generator"]
