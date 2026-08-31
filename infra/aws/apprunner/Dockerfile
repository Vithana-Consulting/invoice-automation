# Combined frontend+backend image for AWS App Runner, which runs exactly
# ONE container per service on ONE exposed port — no room for the
# separate ECS task-with-3-containers pattern used by the Fargate setup.
#
# App Runner terminates TLS itself and gives a stable https://*.awsapprunner.com
# URL, so there's no Caddy here at all — the frontend's own Next.js server
# (already proxying /api/* to the backend over localhost, see
# frontend/next.config.js) is the single thing App Runner points at.
#
# Backend needs Tesseract/Poppler/LibreOffice (see backend/Dockerfile) and
# frontend needs Node — both live in one image here.

FROM node:20-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
# Both baked at build time by Next.js — see infra/aws/scripts/build-and-push.sh
# for why NEXT_PUBLIC_API_URL must stay empty (it runs in the end user's
# browser, not the container) and BACKEND_INTERNAL_URL stays localhost
# (frontend and backend share this one container's network namespace).
ARG BACKEND_INTERNAL_URL=http://localhost:8000
ENV BACKEND_INTERNAL_URL=$BACKEND_INTERNAL_URL
ARG NEXT_PUBLIC_API_URL=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build
# This repo's frontend has no public/ dir (no static assets committed) —
# ensure it exists so the COPY below doesn't fail on a missing source.
RUN mkdir -p public

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libreoffice-writer \
    libgl1 \
    curl \
    ca-certificates \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
RUN mkdir -p data/attachments

WORKDIR /app/frontend
COPY --from=frontend-builder /frontend/.next ./.next
COPY --from=frontend-builder /frontend/public ./public
COPY --from=frontend-builder /frontend/package.json ./package.json
COPY --from=frontend-builder /frontend/node_modules ./node_modules
COPY --from=frontend-builder /frontend/next.config.js ./next.config.js

WORKDIR /app
COPY infra/aws/apprunner/start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:3000 || exit 1

CMD ["/app/start.sh"]
