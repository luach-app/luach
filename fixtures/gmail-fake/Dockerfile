# The Gmail stand-in for a luach test environment (LUACH_GMAIL_API points at it), never production.
# Standard library only: a fixture service with dependencies is a fixture service that breaks.
FROM python:3.12-slim
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin fixture
COPY app.py /app/app.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GMAIL_FAKE_PORT=8080
USER 10001:10001
EXPOSE 8080
CMD ["python", "/app/app.py"]
