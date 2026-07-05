FROM node:20-alpine AS deps

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# --- dev: hot-reload dev server (switch compose target to "dev" to use) -----
FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# --- build: type-check and produce static assets ----------------------------
FROM deps AS build
COPY . .
RUN npm run build

# --- serve: production build served by `vite preview` -----------------------
# vite preview serves dist/ and inherits the /api proxy from server.proxy in
# vite.config.ts, so backend requests keep working without nginx config.
FROM build AS serve
EXPOSE 5173
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "5173"]
