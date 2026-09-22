FROM python:3.13-alpine
ARG VERSION=1.0.0
ENV VERSION=${VERSION}
LABEL org.opencontainers.image.version=${VERSION}
WORKDIR /app
COPY server.py .
USER 10001:10001
CMD ["python", "-u", "server.py"]
