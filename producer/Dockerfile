FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir kafka-python pytz
COPY simulator.py /app/simulator.py
CMD ["python", "-u", "simulator.py"]
