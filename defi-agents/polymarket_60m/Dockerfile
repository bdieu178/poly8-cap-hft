FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
# We use pip to install the project dependencies
RUN pip install --no-cache-dir .

# Copy application files
COPY . .

# Run the harvester
CMD ["python", "data_harvester.py"]
