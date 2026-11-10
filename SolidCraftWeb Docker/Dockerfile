FROM nginxinc/nginx-unprivileged:1.29-alpine

USER root
RUN apk add --no-cache python3 ca-certificates \
 && mkdir -p /app /data/releases \
 && chown -R 101:101 /app /data

COPY --chown=101:101 updater.py /app/updater.py
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --chown=101:101 .build/site/ /opt/solidcraft/baked-release/

ARG IMAGE_VERSION=local
LABEL org.opencontainers.image.version="${IMAGE_VERSION}"

ENV PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD wget -q --spider http://127.0.0.1:8080/ || exit 1

USER 101:101
ENTRYPOINT ["python3", "/app/updater.py"]