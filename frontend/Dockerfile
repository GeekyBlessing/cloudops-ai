# syntax=docker/dockerfile:1

# --- Stage 1: build -------------------------------------------------------
# Vite bakes environment variables starting with VITE_ into the compiled JS
# at BUILD time, not runtime (there's no server-side process reading env
# vars once this is static HTML/JS/CSS served by nginx). That means the
# backend URL has to be supplied as a build ARG, not a runtime -e flag --
# unlike the backend image, changing this value means rebuilding the image.
FROM node:20-alpine AS build
WORKDIR /app

# Dependency-layer caching, same rationale as the backend Dockerfile: copy
# lockfile-relevant files first, install, THEN copy source so editing a
# .tsx file doesn't invalidate the npm install layer.
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json tsconfig.node.json vite.config.ts index.html ./
COPY src/ src/

ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# --- Stage 2: runtime (nginx) ---------------------------------------------
# A static SPA doesn't need Node at runtime at all -- nginx serving the
# `dist/` output is smaller and simpler than running `vite preview` (which
# is explicitly documented by Vite as dev/preview-only, not for production).
FROM nginx:1.27-alpine AS runtime

# react-router-dom's BrowserRouter uses the History API for client-side
# routing (e.g. /incidents/abc-123). Without this, nginx's default config
# would 404 on a hard refresh or direct link to that URL, because no file
# literally named "incidents/abc-123" exists on disk -- only index.html,
# which the router then parses client-side. try_files falls back to
# index.html for exactly that reason.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
