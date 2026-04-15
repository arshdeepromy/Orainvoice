# Dev-friendly setup: Node container that builds static files
# into a shared volume. Watches for source changes and rebuilds.
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install --no-audit && npm install @rollup/rollup-linux-arm64-musl 2>/dev/null || true

COPY . .

ARG VITE_STRIPE_PUBLISHABLE_KEY=""
ENV VITE_STRIPE_PUBLISHABLE_KEY=$VITE_STRIPE_PUBLISHABLE_KEY

# Use pre-built dist on ARM64 (Pi), build on x86
RUN if [ -d dist ] && [ "$(ls -A dist 2>/dev/null)" ]; then \
      echo "Using pre-built dist/"; \
    else \
      npx vite build; \
    fi

# Default: just keep the container alive (nginx serves the files)
CMD ["node", "-e", "setInterval(()=>{},60000)"]
