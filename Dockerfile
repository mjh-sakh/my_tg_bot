# Use a smaller base image
FROM python:3.12.3-slim as builder
LABEL authors="mjh-ao"
ADD requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    find /usr/local \
        \( -type d -a -name test -o -name tests -o -name '__pycache__' \) \
        -o \( -type f -a -name '*.pyc' -o -name '*.pyo' \) \
        -exec rm -rf '{}' +

FROM python:3.12.3-slim
RUN apt-get update && \
    apt-get install -y --no-install-recommends libmagic1=1:5.44-3 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local /usr/local
WORKDIR /app
ADD . /app
ENV PYTHONPATH "${PYTHONPATH}:/app"
CMD ["python", "bot/main.py"]