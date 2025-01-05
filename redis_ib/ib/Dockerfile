FROM debian:bookworm-slim

# Update and upgrade packages
RUN apt-get update && apt-get upgrade

# Install JDK and any needed utilities
RUN apt-get install -y openjdk-17-jre-headless \
                       unzip curl procps vim net-tools \
                       python3 python3-pip python3.11-venv

# Set environment variables to avoid Python buffering and ensure UTF-8 encoding
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# Create necessary directories
RUN mkdir -p /app/logs && \
    mkdir -p /app/data && \
    mkdir -p /app/python

# Set the working directory
WORKDIR /app/python

# Copy files
COPY ./requirements.txt /app/python/requirements.txt
COPY ./app.py /app/python/app.py
COPY ./__init__.py /app/python/__init__.py
COPY ./models.py /app/python/models.py


# Set environment variables
# Set environment variables
RUN python3.11 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN . /opt/venv/bin/activate





# Create and set the working directory
WORKDIR /app/python

# Set up a virtual environment
RUN python -m venv /venv
# Install Python dependencies
RUN pip install -r requirements.txt
# Activate the virtual environment by default
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]