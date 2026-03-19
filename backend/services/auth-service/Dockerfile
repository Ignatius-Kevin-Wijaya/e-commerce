FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Add the app directory to Python path so imports work
ENV PYTHONPATH=/app

EXPOSE 8001

CMD ["uvicorn", "cmd.main:app", "--host", "0.0.0.0", "--port", "8001"]
