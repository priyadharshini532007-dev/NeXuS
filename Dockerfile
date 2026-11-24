FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 NEXUS_DATA=/data TZ=Asia/Kolkata
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY nexus.py cloud_bot.py blueprint.py blueprint_spec.md plans.json sources.json template.html ./
VOLUME /data
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s CMD python -c "import os,time,sys;sys.exit(0 if time.time()-os.path.getmtime('/data/heartbeat')<180 else 1)"
CMD ["python", "cloud_bot.py"]
