FROM python:3.12-slim

# Python buffers stdout by default when it isn't attached to a terminal —
# which is always true in a container — so without this, print() output
# (including startup errors) silently sits in a buffer instead of showing
# up in `docker/podman logs` or the platform's log viewer.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hugging Face Spaces' Docker SDK expects the app on port 7860 by default.
# main.py already reads PORT from the environment (falls back to 8000 for
# local dev), so this is the only Space-specific config needed.
ENV PORT=7860
EXPOSE 7860

CMD ["python3", "main.py"]
