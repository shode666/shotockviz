FROM node:22-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci --frozen-lockfile

COPY . .

# Build args for environment
ARG VITE_API_URL=/api
ARG VITE_WS_URL=wss://localhost
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_WS_URL=$VITE_WS_URL

RUN npm run build

# --- Runtime (TanStack Start uses Node server via Nitro) ---
FROM node:22-alpine

RUN apk add --no-cache curl && \
    addgroup -S stockviz && adduser -S stockviz -G stockviz

WORKDIR /app

COPY --from=builder --chown=stockviz:stockviz /app/.output ./.output
COPY --from=builder --chown=stockviz:stockviz /app/package.json ./package.json

USER stockviz

EXPOSE 3000
CMD ["node", ".output/server/index.mjs"]
