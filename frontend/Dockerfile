# Dev-friendly setup: Node container that builds static files
# into a shared volume. Watches for source changes and rebuilds.
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install --no-audit && npm install @rollup/rollup-linux-arm64-musl 2>/dev/null || true

COPY . .

ARG VITE_STRIPE_PUBLISHABLE_KEY=""
ENV VITE_STRIPE_PUBLISHABLE_KEY=$VITE_STRIPE_PUBLISHABLE_KEY

# Always build fresh — never use pre-existing dist
RUN rm -rf dist && npx vite build

# Default: just keep the container alive (nginx serves the files)
CMD ["node", "-e", "setInterval(()=>{},60000)"]
