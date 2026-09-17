FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY gunicorn.conf.py .
COPY rndplz ./rndplz
COPY pack/data ./pack/data
ENV PORT=10000 RNDPLZ_STATE_DIR=/tmp/rndplz-public-state
USER 10001
EXPOSE 10000
CMD ["gunicorn", "-c", "gunicorn.conf.py", "rndplz.public_web:application"]
